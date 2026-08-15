from __future__ import annotations

import asyncio
import uuid
from typing import Any

from .config import Settings
from .context import ctx_budget, compact_messages, dedupe_tool_result, estimate_messages, estimate_tokens
from .events import EventBus, now_ms
from .memory import SharedMemory
from .models import AgentSnapshot
from .ollama import ModelError, OllamaClient, extract_delta, merge_tool_call_deltas, parse_tool_args
from .parse import extract_text_tool_calls
from .tools.registry import ToolContext, ToolRegistry


WORKER_SYSTEM = """You are iron, a fast local coding agent.
Work only inside the given workspace. Prefer search + precise edit_file over full rewrites.
Keep context small: read only the lines you need.
Use tools. Do not invent file contents.
If native tool calling is unavailable, emit a single JSON object:
{"name":"tool_name","arguments":{...}}
When the task is complete, stop calling tools and write a concise final answer.
If you are blocked, say exactly what you need.
"""


class Agent:
    def __init__(
        self,
        *,
        run_id: str,
        title: str,
        goal: str,
        depth: int,
        parent_id: str | None,
        settings: Settings,
        bus: EventBus,
        client: OllamaClient,
        tools: ToolRegistry,
        memory: SharedMemory,
        workspace: str,
        model: str,
        cancel: asyncio.Event,
        limiter: asyncio.Semaphore,
        spawn_child: Any,
        cloud: bool = False,
    ) -> None:
        self.id = "ag_" + uuid.uuid4().hex[:10]
        self.run_id = run_id
        self.title = title
        self.goal = goal
        self.depth = depth
        self.parent_id = parent_id
        self.settings = settings
        self.bus = bus
        self.client = client
        self.tools = tools
        self.memory = memory
        self.workspace = workspace
        self.model = model
        self.cancel = cancel
        self.limiter = limiter
        self.spawn_child = spawn_child
        self.cloud = cloud
        self.status = "queued"
        self.steps = 0
        self.tokens = 0
        self.prompt_tokens = 0
        self.ctx_window = 0
        self.result = ""
        self.error = ""
        self.created_at = now_ms()
        self.updated_at = self.created_at

    def snapshot(self) -> AgentSnapshot:
        return AgentSnapshot(
            id=self.id,
            run_id=self.run_id,
            parent_id=self.parent_id,
            depth=self.depth,
            title=self.title,
            goal=self.goal,
            status=self.status,  # type: ignore[arg-type]
            model=self.model,
            steps=self.steps,
            tokens=self.tokens,
            prompt_tokens=self.prompt_tokens,
            ctx_window=self.ctx_window,
            result=self.result,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    async def _emit(self, kind: str, **payload: Any) -> None:
        self.updated_at = now_ms()
        await self.bus.emit(
            {
                "type": kind,
                "run_id": self.run_id,
                "agent_id": self.id,
                "parent_id": self.parent_id,
                "depth": self.depth,
                "title": self.title,
                "status": self.status,
                **payload,
            }
        )

    async def _set(self, status: str) -> None:
        self.status = status
        await self._emit("agent.status", agent=self.snapshot().model_dump())

    def _tool_names(self) -> list[str]:
        names = [
            "read_file",
            "write_file",
            "edit_file",
            "list_dir",
            "search",
            "shell",
            "python",
            "memory_get",
            "memory_put",
        ]
        if self.depth < self.settings.max_depth:
            names.append("spawn_subagent")
        names += self.tools.mcp_names()
        return names

    async def _spawn(self, title: str, goal: str) -> str:
        if self.depth >= self.settings.max_depth:
            return "spawn denied: max depth reached"
        return await self.spawn_child(
            parent=self,
            title=title,
            goal=goal,
        )

    async def run(self) -> str:
        await self._set("running")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": WORKER_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Workspace: {self.workspace}\n"
                    f"Depth: {self.depth}/{self.settings.max_depth}\n"
                    f"Task: {self.goal}"
                ),
            },
        ]
        schemas = self.tools.schemas(self._tool_names())
        ctx = ToolContext(
            self.workspace,
            self.memory,
            self._spawn if self.depth < self.settings.max_depth else None,
            cancel=self.cancel,
        )

        try:
            content = ""
            # Limit only inference, never the whole agent. Holding the semaphore
            # across spawn_subagent deadlocks parents waiting on their children.
            for step in range(1, self.settings.max_agent_steps + 1):
                if self.cancel.is_set():
                    await self._set("cancelled")
                    self.result = "cancelled"
                    return self.result
                self.steps = step
                await self._set("thinking")
                self._compact(messages)
                content, tool_calls = await self._infer(messages, schemas)
                if self.cancel.is_set():
                    await self._set("cancelled")
                    self.result = "cancelled"
                    return self.result
                if tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": content or "",
                            "tool_calls": tool_calls,
                        }
                    )
                    for call in tool_calls:
                        if self.cancel.is_set():
                            await self._set("cancelled")
                            self.result = "cancelled"
                            return self.result
                        fn = call.get("function") or {}
                        name = fn.get("name") or ""
                        args = parse_tool_args(fn.get("arguments") or "")
                        call_id = call.get("id") or ("call_" + uuid.uuid4().hex[:8])
                        await self._set("tool")
                        await self._emit("agent.tool", tool=name, args=args, phase="start")
                        result = await self.tools.call(name, args, ctx)
                        clipped = result if len(result) < 12_000 else result[:12_000] + "\n… [truncated]"
                        clipped = dedupe_tool_result(messages, name, clipped)
                        await self._emit("agent.tool", tool=name, args=args, phase="end", result=clipped)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "_tool": name,
                                "content": clipped,
                            }
                        )
                    continue
                self.result = (content or "").strip() or "done"
                await self._set("done")
                await self._emit("agent.result", result=self.result)
                return self.result
            self.result = content or "step limit reached"
            await self._set("done")
            await self._emit("agent.result", result=self.result)
            return self.result
        except asyncio.CancelledError:
            self.result = "cancelled"
            await self._set("cancelled")
            return self.result
        except Exception as exc:
            self.error = str(exc)
            self.result = f"failed: {exc}"
            await self._set("failed")
            await self._emit("agent.error", error=self.error)
            return self.result

    def _ctx_budget(self) -> int:
        num_ctx = min(self.settings.ctx(), 65536 if self.depth else self.settings.ctx())
        return ctx_budget(num_ctx, self.settings.ctx_target)

    def _compact(self, messages: list[dict[str, Any]]) -> None:
        compact_messages(messages, self._ctx_budget())

    async def _infer(self, messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        acc_calls: dict[int, dict[str, Any]] = {}
        parts: list[str] = []
        think: list[str] = []
        num_ctx = min(self.settings.ctx(), 65536 if self.depth else self.settings.ctx())
        prompt_est = estimate_messages(messages)
        out_est = 0
        last_emit = 0
        try:
            async with self.limiter:
                async for chunk in self.client.stream_chat(
                    model=self.model,
                    messages=messages,
                    tools=schemas,
                    num_ctx=num_ctx,
                    cloud=self.cloud,
                ):
                    if self.cancel.is_set():
                        break
                    delta = extract_delta(chunk)
                    if delta["reasoning"]:
                        think.append(delta["reasoning"])
                        await self._emit("agent.think", text=delta["reasoning"])
                        out_est += estimate_tokens(delta["reasoning"])
                    if delta["content"]:
                        parts.append(delta["content"])
                        await self._emit("agent.token", text=delta["content"])
                        out_est += estimate_tokens(delta["content"])
                    if delta["tool_calls"]:
                        merge_tool_call_deltas(acc_calls, delta["tool_calls"])
                        out_est += 12 * len(delta["tool_calls"])
                    if out_est - last_emit >= 256:
                        last_emit = out_est
                        await self._emit_usage(prompt_est + out_est, num_ctx, estimated=True)
                    usage = delta.get("usage") or {}
                    total = usage.get("total_tokens")
                    if total:
                        self.tokens = int(total)
        except ModelError as exc:
            raise RuntimeError(str(exc)) from exc
        calls = [acc_calls[i] for i in sorted(acc_calls)]
        calls = [c for c in calls if (c.get("function") or {}).get("name")]
        text = "".join(parts)
        if not calls:
            calls = extract_text_tool_calls(text, set(self._tool_names()))
        final_prompt = max(prompt_est + out_est, (self.tokens or 0))
        if final_prompt > self.prompt_tokens:
            self.prompt_tokens = final_prompt
        if num_ctx > self.ctx_window:
            self.ctx_window = num_ctx
        await self._emit_usage(final_prompt, num_ctx)
        return text, calls

    async def _emit_usage(self, prompt_tokens: int, num_ctx: int, estimated: bool = False) -> None:
        await self.bus.emit(
            {
                "type": "agent.usage",
                "run_id": self.run_id,
                "agent_id": self.id,
                "prompt_tokens": int(prompt_tokens),
                "num_ctx": int(num_ctx),
                "estimated": estimated,
            }
        )
