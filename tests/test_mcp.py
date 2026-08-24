from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent, Tool

from backend.agent import Agent
from backend.config import Settings
from backend.mcp import (
    MCPManager,
    normalize_config,
    tool_full_name,
    validate_server,
)
from backend.tools.registry import ToolRegistry, ToolSpec


def build_fake_server(tool_count: int = 2) -> Server:
    server = Server("fake")

    @server.list_tools()
    async def _tools() -> list[Tool]:
        base = [
            Tool(
                name="echo",
                description="echo text back",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            Tool(
                name="add.numbers",
                description="add two numbers",
                inputSchema={
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                    "required": [],
                },
            ),
        ]
        for i in range(2, tool_count):
            base.append(
                Tool(
                    name=f"tool_{i}",
                    description=f"extra tool {i}",
                    inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
                )
            )
        base.append(
            Tool(
                name="boom",
                description="always fails",
                inputSchema={"type": "object", "properties": {}},
            )
        )
        return base

    @server.call_tool()
    async def _call(name: str, args: dict[str, Any]) -> list[TextContent]:
        if name == "echo":
            return [TextContent(type="text", text=f"echo:{args.get('text')}")]
        if name == "add.numbers":
            total = float(args.get("a") or 0) + float(args.get("b") or 0)
            return [TextContent(type="text", text=str(total))]
        if name.startswith("tool_"):
            return [TextContent(type="text", text=f"ran {name}")]
        if name == "boom":
            raise ValueError("boom exploded")
        raise ValueError(f"unknown tool {name}")

    return server


class InMemoryManager(MCPManager):
    def __init__(self, servers: dict[str, dict[str, Any]] | None = None, tool_count: int = 2) -> None:
        self._fake = build_fake_server(tool_count)
        super().__init__(servers)

    async def _make_session(self, name: str, cfg: dict[str, Any]):
        cm = create_connected_server_and_client_session(self._fake)
        session = await cm.__aenter__()
        return session, cm.__aexit__(None, None, None)


def test_tool_full_name_sanitizes():
    assert tool_full_name("my server", "list/dir") == "mcp__my_server__list_dir"
    assert tool_full_name("a", "b") == "mcp__a__b"
    assert tool_full_name("demo", "add.numbers") == "mcp__demo__add_numbers"


def test_validate_server():
    assert validate_server("", {}) == "name required"
    assert validate_server("bad name!", {"type": "stdio", "command": "x"}) is not None
    assert validate_server("ok", {"type": "stdio", "command": ""}) == "command required for stdio servers"
    assert validate_server("ok", {"type": "http", "url": ""}) == "url required for http servers"
    assert validate_server("ok", {"type": "weird", "url": "x"}) == "type must be 'stdio' or 'http'"
    assert validate_server("ok", {"type": "stdio", "command": "npx"}) is None
    assert validate_server("ok", {"type": "http", "url": "http://x"}) is None


def test_normalize_config():
    cfg = normalize_config({"type": "stdio", "command": "npx", "args": "a b   c", "env": {}})
    assert cfg["args"] == ["a", "b", "c"]
    assert "env" not in cfg
    cfg = normalize_config({})
    assert cfg["type"] == "stdio"


@pytest.mark.asyncio
async def test_connect_and_list_tools():
    manager = InMemoryManager({"demo": {"type": "stdio", "command": "fake"}})
    await manager.prewarm()
    snap = manager.snapshot()[0]
    assert snap["status"] == "ok"
    assert snap["tools"] == 3
    names = [t["name"] for t in manager._conns["demo"].tools]
    assert "echo" in names and "add.numbers" in names and "boom" in names
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_call_tool():
    manager = InMemoryManager({"demo": {"type": "stdio", "command": "fake"}})
    assert (await manager.call_tool("mcp__demo__echo", {"text": "hi"})) == "echo:hi"
    assert (await manager.call_tool("mcp__demo__add_numbers", {"a": 1, "b": 2})) == "3.0"
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_call_tool_error_and_missing():
    manager = InMemoryManager({"demo": {"type": "stdio", "command": "fake"}})
    out = await manager.call_tool("mcp__demo__boom", {})
    assert out.startswith("mcp error") and "boom exploded" in out
    out = await manager.call_tool("mcp__demo__nope", {})
    assert out == "mcp tool not found: mcp__demo__nope"
    out = await manager.call_tool("mcp__other__echo", {})
    assert out.startswith("mcp tool unavailable") or out.startswith("mcp error")
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_registry_sync():
    manager = InMemoryManager({"demo": {"type": "stdio", "command": "fake"}})
    await manager.prewarm()
    registry = ToolRegistry()
    registry.sync_mcp(manager)
    assert set(registry.mcp_names()) == {
        "mcp__demo__echo",
        "mcp__demo__add_numbers",
        "mcp__demo__boom",
    }
    schemas = registry.schemas(["mcp__demo__echo"])
    assert schemas[0]["function"]["name"] == "mcp__demo__echo"
    assert schemas[0]["function"]["parameters"]["properties"]["text"]["type"] == "string"
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_registry_handlers_route_to_their_own_tool():
    """Regression: handlers used to capture the loop variable by reference,
    so every MCP tool routed to the last tool in the last server."""
    manager = InMemoryManager(
        {"alpha": {"type": "stdio", "command": "fake"}, "beta": {"type": "stdio", "command": "fake"}}
    )
    await manager.prewarm()
    registry = ToolRegistry()
    registry.sync_mcp(manager)
    echo = await registry._tools["mcp__alpha__echo"].handler({"text": "hi"}, None)
    add = await registry._tools["mcp__alpha__add_numbers"].handler({"a": 1, "b": 2}, None)
    assert echo == "echo:hi"
    assert add == "3.0"
    # each server's own copy of the same-named tool routes to that server
    b_echo = await registry._tools["mcp__beta__echo"].handler({"text": "yo"}, None)
    assert b_echo == "echo:yo"
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_snapshot_status_after_failed_connect():
    manager = MCPManager({"broken": {"type": "http", "url": "http://127.0.0.1:1/mcp"}})
    await manager.prewarm()
    snap = manager.snapshot()[0]
    assert snap["status"].startswith("error:")
    assert snap["tools"] == 0
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_configure_reconnects_changed():
    manager = InMemoryManager({"demo": {"type": "stdio", "command": "fake"}})
    await manager.prewarm()
    assert manager.snapshot()[0]["status"] == "ok"
    manager.configure({"demo": {"type": "stdio", "command": "fake", "args": ["--x"]}})
    await manager.prewarm()
    assert manager.snapshot()[0]["status"] == "ok"
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_probe():
    manager = InMemoryManager({"demo": {"type": "stdio", "command": "fake"}})
    tools = await manager.probe("demo")
    assert "echo" in tools and "boom" in tools
    with pytest.raises(KeyError):
        await manager.probe("missing")
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_max_exposed_cap():
    manager = InMemoryManager({"srv": {"type": "stdio", "command": "x"}}, tool_count=60)
    await manager.prewarm()
    specs = manager.tool_specs()
    assert len(specs) == 40
    await manager.disconnect_all()


def test_settings_roundtrip():
    servers = {"demo": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}}
    settings = Settings(mcp_servers=servers)
    data = settings.model_dump()
    assert data["mcp_servers"] == servers
    again = Settings.model_validate(data)
    assert again.mcp_servers == servers


@pytest.mark.asyncio
async def test_real_stdio_server():
    import sys
    from pathlib import Path

    script = str(Path(__file__).resolve().parent / "fake_stdio_server.py")
    manager = MCPManager({"real": {"type": "stdio", "command": sys.executable, "args": [script]}})
    await manager.prewarm()
    snap = manager.snapshot()[0]
    assert snap["status"] == "ok", snap
    assert snap["tools"] == 1
    assert (await manager.call_tool("mcp__real__ping", {})) == "pong"
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_remove_and_shutdown_leave_no_loop_errors():
    import sys
    from pathlib import Path

    loop = asyncio.get_running_loop()
    caught: list[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda l, ctx: caught.append(ctx))

    script = str(Path(__file__).resolve().parent / "fake_stdio_server.py")
    try:
        manager = MCPManager(
            {
                "a": {"type": "stdio", "command": sys.executable, "args": [script]},
                "b": {"type": "stdio", "command": sys.executable, "args": [script]},
            }
        )
        await manager.prewarm()
        assert (await manager.call_tool("mcp__a__ping", {})) == "pong"
        manager.configure({"b": {"type": "stdio", "command": sys.executable, "args": [script]}})
        await asyncio.sleep(0.4)
        assert not caught, caught
        await manager.disconnect_all()
        await asyncio.sleep(0.4)
        assert not caught, caught
    finally:
        loop.set_exception_handler(previous)


def test_agent_tool_names_include_mcp():
    registry = ToolRegistry()

    async def noop(args, ctx):
        return "ok"

    registry.register(ToolSpec("mcp__demo__echo", "echo", {"type": "object", "properties": {}}, noop))

    agent = object.__new__(Agent)
    agent.settings = types.SimpleNamespace(max_depth=2)
    agent.depth = 1
    agent.tools = registry
    names = agent._tool_names()
    assert "mcp__demo__echo" in names
    assert "read_file" in names
    assert "spawn_subagent" in names
    agent.depth = 2
    assert "spawn_subagent" not in agent._tool_names()
