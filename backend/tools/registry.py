from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from . import exec as exec_mod
from . import fs
from . import shell as shell_mod
from . import web

Handler = Callable[[dict[str, Any], "ToolContext"], Awaitable[str]]


class ToolContext:
    def __init__(
        self,
        workspace: str,
        memory: Any,
        spawn: Callable[..., Awaitable[str]] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> None:
        self.workspace = workspace
        self.memory = memory
        self.spawn = spawn
        self.cancel = cancel


class ToolSpec:
    def __init__(self, name: str, description: str, parameters: dict[str, Any], handler: Handler) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return [spec.openai() for spec in self._tools.values()]
        return [self._tools[n].openai() for n in names if n in self._tools]

    async def call(self, name: str, args: dict[str, Any], ctx: ToolContext) -> str:
        spec = self._tools.get(name)
        if spec is None:
            return f"unknown tool: {name}"
        try:
            return await spec.handler(args, ctx)
        except Exception as exc:
            return f"tool error ({name}): {exc}"

    def sync_mcp(self, manager: Any) -> None:
        for name in [n for n in self._tools if n.startswith("mcp__")]:
            del self._tools[name]
        for spec in manager.tool_specs():
            self._tools[spec.name] = spec

    def mcp_names(self) -> list[str]:
        return [n for n in self._tools if n.startswith("mcp__")]


def _str(args: dict[str, Any], key: str, default: str = "") -> str:
    value = args.get(key, default)
    return default if value is None else str(value)


def _int(args: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError, OverflowError):
        return default


def _bool(args: dict[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def _read(args: dict[str, Any], ctx: ToolContext) -> str:
    path = _str(args, "path")
    offset = _int(args, "offset", 1)
    limit = _int(args, "limit", 400)
    cache = ctx.memory if ctx.memory is not None else None
    key = (path, offset, limit)
    try:
        if cache is not None and hasattr(cache, "file_cache_get"):
            stat = fs.resolve_workspace(ctx.workspace, path).stat()
            hit = cache.file_cache_get(key)
            if hit and hit[0] == stat.st_mtime and hit[1] == stat.st_size:
                return hit[2]
            out = await asyncio.to_thread(fs.read_file, ctx.workspace, path, offset, limit)
            cache.file_cache_put(key, stat.st_mtime, stat.st_size, out)
            return out
    except Exception:
        pass
    return await asyncio.to_thread(fs.read_file, ctx.workspace, path, offset, limit)


async def _write(args: dict[str, Any], ctx: ToolContext) -> str:
    return await asyncio.to_thread(fs.write_file, ctx.workspace, _str(args, "path"), _str(args, "content"))


async def _edit(args: dict[str, Any], ctx: ToolContext) -> str:
    return await asyncio.to_thread(
        fs.edit_file,
        ctx.workspace,
        _str(args, "path"),
        _str(args, "old_string"),
        _str(args, "new_string"),
        _bool(args, "replace_all"),
    )


async def _ls(args: dict[str, Any], ctx: ToolContext) -> str:
    return await asyncio.to_thread(fs.list_dir, ctx.workspace, _str(args, "path", "."), _str(args, "glob", "*"))


async def _search(args: dict[str, Any], ctx: ToolContext) -> str:
    return await asyncio.to_thread(fs.search_text, ctx.workspace, _str(args, "query"), _str(args, "path", "."), _str(args, "glob"))


async def _shell(args: dict[str, Any], ctx: ToolContext) -> str:
    return await shell_mod.run_shell(ctx.workspace, _str(args, "command"), _int(args, "timeout", 60), cancel=ctx.cancel)


async def _python(args: dict[str, Any], ctx: ToolContext) -> str:
    return await exec_mod.run_python(_str(args, "code"), _int(args, "timeout", 30), cwd=ctx.workspace, cancel=ctx.cancel)


async def _memory_get(args: dict[str, Any], ctx: ToolContext) -> str:
    if not ctx.memory:
        return "memory unavailable"
    key = _str(args, "key")
    if key:
        value = ctx.memory.get(key)
        return "(missing)" if value is None else str(value)
    items = ctx.memory.all()
    if not items:
        return "(empty)"
    return "\n".join(f"{k}: {v}" for k, v in items.items())


async def _memory_put(args: dict[str, Any], ctx: ToolContext) -> str:
    if not ctx.memory:
        return "memory unavailable"
    ctx.memory.put(_str(args, "key"), _str(args, "value"))
    return "stored"


async def _spawn(args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.spawn is None:
        return "spawn unavailable at this depth"
    title = _str(args, "title") or "subtask"
    goal = _str(args, "goal")
    if not goal:
        return "goal required"
    return await ctx.spawn(title=title, goal=goal)


def builtin_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "read_file",
            "Read a workspace file with numbered lines. Prefer this before editing.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "1-based start line"},
                    "limit": {"type": "integer", "description": "max lines"},
                },
                "required": ["path"],
            },
            _read,
        )
    )
    registry.register(
        ToolSpec(
            "write_file",
            "Create or overwrite a workspace file. Prefer edit_file for existing files.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            _write,
        )
    )
    registry.register(
        ToolSpec(
            "edit_file",
            "Precise search-and-replace in a workspace file. old_string must match uniquely unless replace_all.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
            _edit,
        )
    )
    registry.register(
        ToolSpec(
            "list_dir",
            "List files in a workspace directory.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}, "glob": {"type": "string"}},
                "required": [],
            },
            _ls,
        )
    )
    registry.register(
        ToolSpec(
            "search",
            "Regex or literal search across the workspace. Returns path:line: snippet.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string", "description": "filename glob like *.py"},
                },
                "required": ["query"],
            },
            _search,
        )
    )
    registry.register(
        ToolSpec(
            "shell",
            "Run a shell command inside the workspace. Use for tests, git, builds.",
            {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
            _shell,
        )
    )
    registry.register(
        ToolSpec(
            "python",
            "Execute a short Python snippet in an isolated temp file. Return stdout/stderr.",
            {
                "type": "object",
                "properties": {"code": {"type": "string"}, "timeout": {"type": "integer"}},
                "required": ["code"],
            },
            _python,
        )
    )
    registry.register(
        ToolSpec(
            "memory_get",
            "Read shared memory. Omit key to list all entries.",
            {"type": "object", "properties": {"key": {"type": "string"}}, "required": []},
            _memory_get,
        )
    )
    registry.register(
        ToolSpec(
            "memory_put",
            "Write an important finding into shared memory for other agents.",
            {
                "type": "object",
                "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                "required": ["key", "value"],
            },
            _memory_put,
        )
    )
    registry.register(
        ToolSpec(
            "web_search",
            "Search the web (DuckDuckGo, no key). Returns ranked title/url/snippet results. Use to look up docs, APIs, errors.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "default 6, max 10"},
                },
                "required": ["query"],
            },
            web.handler_search,
        )
    )
    registry.register(
        ToolSpec(
            "web_fetch",
            "Fetch a URL and return its readable text. Use after web_search to read a page. Caps output at ~8000 chars.",
            {
                "type": "object",
                "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
                "required": ["url"],
            },
            web.handler_fetch,
        )
    )
    registry.register(
        ToolSpec(
            "spawn_subagent",
            "Spawn a child agent for a discrete subtask. Only available when depth < 2. Returns the child's final result.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "goal": {"type": "string", "description": "self-contained instructions for the child"},
                },
                "required": ["goal"],
            },
            _spawn,
        )
    )
    return registry
