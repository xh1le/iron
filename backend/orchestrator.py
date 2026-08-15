from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from .agent import Agent
from .config import Settings
from .events import EventBus, now_ms
from .memory import SharedMemory
from .models import RunSnapshot
from .ollama import ModelError, OllamaClient, extract_delta, merge_tool_call_deltas, parse_tool_args
from .parse import extract_text_tool_calls
from .tools.registry import ToolRegistry

ORCH_SYSTEM = """You are iron's orchestrator. Decompose the user's goal into independent parallel tasks.
Prefer many small agents over one large agent. Each task must be self-contained.
Never exceed depth 2 for descendants (you are depth 0; workers are 1; their children are 2).

You have tools:
- spawn_task: launch a worker agent. It will run to completion and return a result.
- memory_get / memory_put: share facts between tasks.
- ask_user: pause the run and request human input. Use only when truly blocked.
- finish: end the run with a final answer for the user.

Strategy:
1. Inspect the goal. If it is a single tiny action, spawn one worker.
2. Otherwise spawn 2–8 independent workers in one turn (they run in parallel).
3. Read their results. Spawn follow-ups only if needed.
4. Call finish when the goal is complete.

Do not write files yourself. Workers do the work.
If native tool calling is unavailable, emit JSON:
{"name":"spawn_task","arguments":{"title":"...","goal":"..."}}
or {"name":"finish","arguments":{"summary":"..."}}
or {"tasks":[{"title":"...","goal":"..."}]}
"""


class Run:
    def __init__(
        self,
        *,
        goal: str,
        settings: Settings,
        bus: EventBus,
        client: OllamaClient,
        tools: ToolRegistry,
        workspace: str,
        model: str,
        orch_model: str,
        cloud: bool,
    ) -> None:
        self.id = "run_" + uuid.uuid4().hex[:10]
        self.goal = goal
        self.settings = settings
        self.bus = bus
        self.client = client
        self.tools = tools
        self.workspace = workspace
        self.model = model
        self.orch_model = orch_model
        self.cloud = cloud
        self.status = "queued"
        self.result = ""
        self.error = ""
        self.created_at = now_ms()
        self.updated_at = self.created_at
        self.memory = SharedMemory()
        self.cancel = asyncio.Event()
        self.limiter = asyncio.Semaphore(max(1, settings.max_concurrent))
        self.agents: dict[str, Agent] = {}
        self.task: asyncio.Task[None] | None = None
        self._need_input: asyncio.Future[str] | None = None
        self.question = ""
        self.chat_id = ""
        self.project_id = ""
        self.extra_context = ""
        self.on_done: Any = None

    def snapshot(self) -> RunSnapshot:
        agents = [a.snapshot() for a in self.agents.values()]
        agents.sort(key=lambda a: a.created_at)
        return RunSnapshot(
            id=self.id,
            goal=self.goal,
            status=self.status,  # type: ignore[arg-type]
            model=self.orch_model,
            created_at=self.created_at,
            updated_at=self.updated_at,
            result=self.result,
            error=self.error,
            chat_id=self.chat_id,
            project_id=self.project_id,
            agents=agents,
        )

    async def _emit(self, kind: str, **payload: Any) -> None:
        self.updated_at = now_ms()
        await self.bus.emit({"type": kind, "run_id": self.id, "status": self.status, **payload})

    async def _set(self, status: str) -> None:
        self.status = status
        await self._emit("run.status", run=self.snapshot().model_dump())

    def request_cancel(self) -> None:
        self.cancel.set()
        if self._need_input and not self._need_input.done():
            self._need_input.cancel()

    def provide_input(self, text: str) -> bool:
        if self._need_input and not self._need_input.done():
            self._need_input.set_result(text)
            return True
        return False

    async def spawn_agent(self, *, parent: Agent | None, title: str, goal: str) -> str:
        # Orchestrator is not counted. Direct workers are depth 1; their children are depth 2.
        depth = 1 if parent is None else parent.depth + 1
        if depth > self.settings.max_depth:
            return "spawn denied: max depth reached"
        agent = Agent(
            run_id=self.id,
            title=title[:80] or "worker",
            goal=goal,
            depth=depth,
            parent_id=None if parent is None else parent.id,
            settings=self.settings,
            bus=self.bus,
            client=self.client,
            tools=self.tools,
            memory=self.memory,
            workspace=self.workspace,
            model=self.model,
            cancel=self.cancel,
            limiter=self.limiter,
            spawn_child=lambda parent, title, goal: self.spawn_agent(parent=parent, title=title, goal=goal),
            cloud=False,
        )
        self.agents[agent.id] = agent
        await self._emit("agent.spawn", agent=agent.snapshot().model_dump())
        return await agent.run()

    async def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name=f"iron-run-{self.id}")

    async def _loop(self) -> None:
        await self._set("running")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ORCH_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Workspace: {self.workspace}\n"
                    f"Max concurrent workers: {self.settings.max_concurrent}\n"
                    + (f"\nEarlier conversation:\n{self.extra_context}\n" if self.extra_context else "")
                    + f"Goal:\n{self.goal}"
                ),
            },
        ]
        schemas = self.tools.schemas(["memory_get", "memory_put"]) + [
            {
                "type": "function",
                "function": {
                    "name": "spawn_task",
                    "description": "Spawn a worker agent for a discrete task. Multiple calls in one turn run in parallel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "goal": {"type": "string"},
                        },
                        "required": ["goal"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_user",
                    "description": "Pause and ask the human a question.",
                    "parameters": {
                        "type": "object",
                        "properties": {"question": {"type": "string"}},
                        "required": ["question"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Complete the run with a final answer.",
                    "parameters": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                    },
                },
            },
        ]

        try:
            for _round in range(1, self.settings.max_orchestrator_rounds + 1):
                if self.cancel.is_set():
                    await self._set("cancelled")
                    self.result = "cancelled"
                    self._persist()
                    return
                content, tool_calls = await self._infer(messages, schemas)
                if self.cancel.is_set():
                    await self._set("cancelled")
                    self.result = "cancelled"
                    self._persist()
                    return
                if not tool_calls and _round == 1:
                    # Small models often narrate instead of calling tools.
                    # First round: force a single worker so the goal still executes.
                    tool_calls = [
                        {
                            "id": "call_autowork",
                            "type": "function",
                            "function": {
                                "name": "spawn_task",
                                "arguments": json.dumps({"title": "worker", "goal": self.goal}),
                            },
                        }
                    ]
                if not tool_calls:
                    self.result = (content or "").strip() or "done"
                    await self._set("done")
                    await self._emit("run.result", result=self.result)
                    self._persist()
                    return
                messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})

                spawn_jobs: list[tuple[dict[str, Any], str, str]] = []
                other: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    args = parse_tool_args(fn.get("arguments") or "")
                    if name == "spawn_task":
                        spawn_jobs.append((call, str(args.get("title") or "worker"), str(args.get("goal") or "")))
                    else:
                        other.append((call, name, args))

                if spawn_jobs:
                    await self._emit("run.plan", tasks=[{"title": t, "goal": g} for _, t, g in spawn_jobs])
                    results = await asyncio.gather(
                        *[self.spawn_agent(parent=None, title=title, goal=goal) for _, title, goal in spawn_jobs],
                        return_exceptions=True,
                    )
                    for (call, title, _goal), result in zip(spawn_jobs, results, strict=False):
                        if isinstance(result, Exception):
                            text = f"worker '{title}' failed: {result}"
                        else:
                            text = f"worker '{title}' finished:\n{result}"
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id") or "call_spawn",
                                "content": text[:12_000],
                            }
                        )

                finished = False
                for call, name, args in other:
                    call_id = call.get("id") or ("call_" + uuid.uuid4().hex[:8])
                    if name == "finish":
                        self.result = str(args.get("summary") or content or "done")
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": "ok"})
                        finished = True
                    elif name == "ask_user":
                        question = str(args.get("question") or "Need input")
                        self.question = question
                        await self._set("needs_input")
                        await self._emit("run.ask", question=question)
                        answer = await self._wait_input()
                        if self.cancel.is_set():
                            await self._set("cancelled")
                            self.result = "cancelled"
                            self._persist()
                            return
                        await self._set("running")
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": f"user: {answer}"})
                    elif name in {"memory_get", "memory_put"}:
                        from .tools.registry import ToolContext

                        text = await self.tools.call(name, args, ToolContext(self.workspace, self.memory, None))
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": text})
                    else:
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": f"unknown tool {name}"})

                if finished:
                    await self._set("done")
                    await self._emit("run.result", result=self.result)
                    self._persist()
                    return

            self.result = self.result or "orchestrator round limit reached"
            await self._set("done")
            await self._emit("run.result", result=self.result)
            self._persist()
        except asyncio.CancelledError:
            self.result = "cancelled"
            await self._set("cancelled")
            self._persist()
        except Exception as exc:
            self.error = str(exc)
            self.result = f"failed: {exc}"
            await self._set("failed")
            await self._emit("run.error", error=self.error)
            self._persist()

    def _persist(self) -> None:
        if callable(self.on_done):
            try:
                self.on_done(self)
            except Exception:
                pass

    async def _wait_input(self) -> str:
        loop = asyncio.get_running_loop()
        self._need_input = loop.create_future()
        try:
            return await self._need_input
        except asyncio.CancelledError:
            return ""
        finally:
            self._need_input = None

    async def _infer(self, messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        acc_calls: dict[int, dict[str, Any]] = {}
        parts: list[str] = []
        try:
            async with self.limiter:
                async for chunk in self.client.stream_chat(
                    model=self.orch_model,
                    messages=messages,
                    tools=schemas,
                    num_ctx=self.settings.ctx(),
                    cloud=self.cloud,
                ):
                    if self.cancel.is_set():
                        break
                    delta = extract_delta(chunk)
                    if delta["reasoning"]:
                        await self._emit("run.think", text=delta["reasoning"])
                    if delta["content"]:
                        parts.append(delta["content"])
                        await self._emit("run.token", text=delta["content"])
                    if delta["tool_calls"]:
                        merge_tool_call_deltas(acc_calls, delta["tool_calls"])
        except ModelError as exc:
            raise RuntimeError(str(exc)) from exc
        calls = [acc_calls[i] for i in sorted(acc_calls)]
        calls = [c for c in calls if (c.get("function") or {}).get("name")]
        text = "".join(parts)
        if not calls:
            calls = extract_text_tool_calls(text, {"spawn_task", "finish", "ask_user", "memory_get", "memory_put"})
        return text, calls


class Engine:
    def __init__(self, settings: Settings, bus: EventBus, tools: ToolRegistry) -> None:
        self.settings = settings
        self.bus = bus
        self.tools = tools
        self.client = OllamaClient(settings)
        self.runs: dict[str, Run] = {}

    def reload(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OllamaClient(settings)

    async def create_run(
        self,
        goal: str,
        workspace: str | None = None,
        model: str | None = None,
        *,
        chat_id: str = "",
        project_id: str = "",
        extra_context: str = "",
        on_done: Any = None,
    ) -> Run:
        ws = workspace or self.settings.workspace
        worker_model = model or self.settings.resolved_model()
        orch_model = self.settings.cloud_model if self.settings.use_cloud_orchestrator and self.settings.cloud_model else self.settings.resolved_orchestrator_model()
        run = Run(
            goal=goal,
            settings=self.settings,
            bus=self.bus,
            client=self.client,
            tools=self.tools,
            workspace=ws,
            model=worker_model,
            orch_model=orch_model,
            cloud=bool(self.settings.use_cloud_orchestrator and self.settings.cloud_base_url),
        )
        run.chat_id = chat_id
        run.project_id = project_id
        run.extra_context = extra_context
        run.on_done = on_done
        self.runs[run.id] = run
        await run.start()
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def recent(self, limit: int = 30) -> list[RunSnapshot]:
        items = [r.snapshot() for r in self.runs.values()]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return items[:limit]
