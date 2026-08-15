from __future__ import annotations

import asyncio
import datetime
import re
import time
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent

from .tools.registry import ToolSpec

MAX_EXPOSED_TOOLS = 40
NAME_CLEAN = re.compile(r"[^a-zA-Z0-9_]+")

_STOP: Any = object()


def _clean(part: str) -> str:
    return NAME_CLEAN.sub("_", part).strip("_")[:48] or "tool"


def tool_full_name(server: str, tool: str) -> str:
    return f"mcp__{_clean(server)}__{_clean(tool)}"


def validate_server(name: str, cfg: dict[str, Any]) -> str | None:
    name = (name or "").strip()
    if not name:
        return "name required"
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name):
        return "name may only contain letters, digits, - and _"
    ctype = str(cfg.get("type") or "stdio")
    if ctype not in {"stdio", "http"}:
        return "type must be 'stdio' or 'http'"
    if ctype == "stdio":
        if not str(cfg.get("command") or "").strip():
            return "command required for stdio servers"
    else:
        if not str(cfg.get("url") or "").strip():
            return "url required for http servers"
    return None


def normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in cfg.items():
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        if key == "args" and isinstance(value, str):
            out[key] = [a for a in re.split(r"\s+", value.strip()) if a]
        else:
            out[key] = value
    out.setdefault("type", "stdio")
    return out


def _render_result(result: CallToolResult) -> tuple[str, bool]:
    parts: list[str] = []
    for item in result.content or []:
        if isinstance(item, TextContent):
            parts.append(item.text)
        elif isinstance(item, ImageContent):
            parts.append("[image result omitted]")
        elif isinstance(item, EmbeddedResource):
            parts.append("[embedded resource result omitted]")
        else:
            parts.append(str(item))
    return "\n".join(parts).strip() or "(empty result)", bool(result.isError)


@dataclass
class _Request:
    tool: str
    args: dict[str, Any]
    future: asyncio.Future[Any] = field(default_factory=asyncio.Future)


class _Connection:
    """A live MCP connection. All protocol I/O happens in one owner task so the
    session is entered and exited in the same task (anyio cancel scopes require
    it). Requests are serialized through a queue."""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self.cfg = cfg
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.session: ClientSession | None = None
        self.tools: list[dict[str, Any]] = []
        self.status = "idle"


class MCPManager:
    def __init__(self, servers: dict[str, dict[str, Any]] | None = None) -> None:
        self.servers: dict[str, dict[str, Any]] = {}
        self._conns: dict[str, _Connection] = {}
        self._route: dict[str, tuple[str, str]] = {}
        self.configure(servers or {})

    def configure(self, servers: dict[str, dict[str, Any]]) -> None:
        servers = {name: normalize_config(cfg) for name, cfg in (servers or {}).items()}
        for name, conn in list(self._conns.items()):
            if name not in servers or conn.cfg != servers[name]:
                self._close_now(name)
        for name, cfg in servers.items():
            if name not in self._conns:
                self._start(name, cfg)
        self.servers = servers
        self._rebuild_route()

    def _start(self, name: str, cfg: dict[str, Any]) -> None:
        conn = _Connection(name, cfg)
        self._conns[name] = conn
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        conn.task = loop.create_task(self._owner(conn), name=f"iron-mcp-{name}")

    def _close_now(self, name: str) -> None:
        conn = self._conns.pop(name, None)
        if conn is None:
            return
        if conn.task is not None and not conn.task.done():
            conn.queue.put_nowait(_STOP)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._await_close(conn))

    async def _await_close(self, conn: _Connection) -> None:
        try:
            await asyncio.shield(conn.task)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _owner(self, conn: _Connection) -> None:
        conn.status = "connecting"
        try:
            session, cleanup = await self._make_session(conn.name, conn.cfg)
        except Exception as exc:
            conn.status = f"error: {exc}"
            return
        conn.session = session
        try:
            result = await session.list_tools()
        except Exception as exc:
            conn.status = f"error: {exc}"
            try:
                await cleanup
            except BaseException:
                pass
            conn.session = None
            return
        tools = []
        for tool in result.tools:
            schema = tool.inputSchema or {}
            if not isinstance(schema, dict) or schema.get("type") != "object":
                schema = {"type": "object", "properties": {}}
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": schema,
                }
            )
        conn.tools = tools
        conn.status = "ok"
        self._rebuild_route()
        try:
            while True:
                request = await conn.queue.get()
                if request is _STOP:
                    break
                try:
                    out = await session.call_tool(request.tool, request.args)
                    if not request.future.cancelled():
                        request.future.set_result(out)
                except asyncio.CancelledError:
                    request.future.cancel()
                    raise
                except Exception as exc:
                    if not request.future.cancelled():
                        request.future.set_exception(exc)
        finally:
            conn.session = None
            conn.status = "closed"
            try:
                await cleanup
            except BaseException:
                pass

    async def _make_session(self, name: str, cfg: dict[str, Any]) -> tuple[ClientSession, Any]:
        """Open a ClientSession for a server config; returns (session, cleanup coroutine)."""
        ctype = str(cfg.get("type") or "stdio")
        timeout = float(cfg.get("timeout") or 30)
        read_timeout: Any = datetime.timedelta(seconds=timeout)
        if ctype == "http":
            url = str(cfg.get("url") or "")
            if not url:
                raise ValueError("http server requires 'url'")
            headers: dict[str, str] | None = dict(cfg.get("headers") or {}) or None
            transport = streamablehttp_client(url, headers=headers, timeout=timeout)
        else:
            command = str(cfg.get("command") or "")
            if not command:
                raise ValueError("stdio server requires 'command'")
            env: dict[str, str] | None = dict(cfg.get("env") or {}) or None
            params = StdioServerParameters(command=command, args=list(cfg.get("args") or []), env=env)
            transport = stdio_client(params)
        read, write = await transport.__aenter__()

        async def transport_cleanup() -> None:
            await transport.__aexit__(None, None, None)

        session = ClientSession(read, write, read_timeout_seconds=read_timeout)
        await session.__aenter__()
        await session.initialize()

        async def session_cleanup() -> None:
            try:
                await session.__aexit__(None, None, None)
            finally:
                await transport_cleanup()

        return session, session_cleanup()

    def _rebuild_route(self) -> None:
        route: dict[str, tuple[str, str]] = {}
        for name, conn in self._conns.items():
            for tool in conn.tools:
                route[tool_full_name(name, tool["name"])] = (name, tool["name"])
        self._route = route

    async def _wait_ready(self, name: str, seconds: float = 12.0) -> None:
        deadline = time.monotonic() + seconds
        while (
            self._conns.get(name) is not None
            and self._conns[name].status in {"idle", "connecting"}
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.05)

    async def probe(self, name: str) -> list[str]:
        """Ensure a connection is live and return its tool names."""
        if name not in self.servers:
            raise KeyError(f"no such server: {name}")
        conn = self._conns.get(name)
        if conn is None or conn.session is None:
            self._close_now(name)
            self._start(name, self.servers[name])
            await self._wait_ready(name, seconds=15)
            conn = self._conns.get(name)
        if conn is None or conn.session is None:
            raise RuntimeError(conn.status if conn is not None else "idle")
        return [tool["name"] for tool in conn.tools]

    async def prewarm(self) -> None:
        for name in list(self._conns):
            await self._wait_ready(name, seconds=15)

    async def disconnect_all(self) -> None:
        pending: list[asyncio.Task[None]] = []
        for name, conn in list(self._conns.items()):
            self._conns.pop(name, None)
            if conn.task is not None and not conn.task.done():
                conn.queue.put_nowait(_STOP)
                pending.append(conn.task)
        if pending:
            try:
                await asyncio.shield(asyncio.gather(*pending, return_exceptions=True))
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, cfg in sorted(self.servers.items()):
            conn = self._conns.get(name)
            status = conn.status if conn is not None else "idle"
            out.append(
                {
                    "name": name,
                    "type": str(cfg.get("type") or "stdio"),
                    "command": str(cfg.get("command") or ""),
                    "url": str(cfg.get("url") or ""),
                    "tools": len(conn.tools) if conn is not None else 0,
                    "status": str(status)[:160],
                }
            )
        return out

    def tool_specs(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for name in sorted(self._conns):
            conn = self._conns[name]
            for tool in conn.tools:
                full = tool_full_name(name, tool["name"])

                async def handler(args: dict[str, Any], _ctx: Any) -> str:
                    return await self.call_tool(full, args)

                specs.append(
                    ToolSpec(
                        full,
                        tool["description"] or f"Tool provided by the '{name}' MCP server.",
                        dict(tool["inputSchema"]),
                        handler,
                    )
                )
                if len(specs) >= MAX_EXPOSED_TOOLS:
                    return specs
        return specs

    async def call_tool(self, full: str, args: dict[str, Any]) -> str:
        route = self._route.get(full)
        if route is None:
            server = self._server_for(full)
            if server is None:
                return f"mcp tool unavailable: {full} (no such server)"
            if server not in self._conns:
                cfg = self.servers.get(server)
                if cfg is None:
                    return f"mcp tool unavailable: {full} (no such server)"
                self._start(server, cfg)
            await self._wait_ready(server)
            route = self._route.get(full)
            if route is None:
                return f"mcp tool not found: {full}"
        server, tool = route
        conn = self._conns.get(server)
        if conn is None or conn.session is None:
            self._close_now(server)
            cfg = self.servers.get(server)
            if cfg is not None:
                self._start(server, cfg)
            await self._wait_ready(server, seconds=5)
            conn = self._conns.get(server)
            if conn is None or conn.session is None:
                return f"mcp error ({server}): server unavailable — {conn.status if conn else 'idle'}"
        timeout = float(conn.cfg.get("timeout") or 120)
        request = _Request(tool, dict(args or {}))
        try:
            conn.queue.put_nowait(request)
        except asyncio.QueueFull:
            return f"mcp error ({server}): queue full"
        try:
            result = await asyncio.wait_for(request.future, timeout=timeout)
        except asyncio.TimeoutError:
            self._close_now(server)
            return f"mcp error ({server}/{tool}): timed out after {timeout:.0f}s"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return f"mcp error ({server}/{tool}): {exc}"
        text, is_error = _render_result(result)
        if is_error:
            return f"mcp error ({server}/{tool}): {text}"
        return text

    def _server_for(self, full: str) -> str | None:
        if not full.startswith("mcp__"):
            return None
        matches = [
            name
            for name in self.servers
            if full.startswith(f"mcp__{_clean(name)}__") or full == f"mcp__{_clean(name)}"
        ]
        if not matches:
            return None
        return max(matches, key=len)
