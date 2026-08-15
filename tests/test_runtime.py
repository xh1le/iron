import asyncio
import json
from typing import Any

from backend.config import Settings
from backend.events import EventBus
from backend.orchestrator import Engine, Run
from backend.tools.registry import builtin_tools


def chunk_tool(name: str, args: dict[str, Any], index: int = 0, call_id: str = "c1") -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": call_id,
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def chunk_text(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}


class FakeClient:
    def __init__(self) -> None:
        self.orch = 0

    def _kind(self, messages: list[dict[str, Any]]) -> str:
        blob = "\n".join(str(m.get("content") or "") for m in messages)
        if "You are iron's orchestrator" in str(messages[0].get("content") if messages else ""):
            return "orch"
        if "Depth: 2/" in blob:
            return "child"
        return "worker"

    async def stream_chat(self, **kwargs: Any):
        messages = kwargs.get("messages") or []
        kind = self._kind(messages)
        has_tool = any(m.get("role") == "tool" for m in messages)
        if kind == "orch":
            self.orch += 1
            if not has_tool:
                yield chunk_tool("spawn_task", {"title": "alpha", "goal": "write file alpha.txt containing ALPHA"}, 0, "a")
                yield chunk_tool("spawn_task", {"title": "beta", "goal": "write file beta.txt containing BETA"}, 1, "b")
                return
            yield chunk_tool("finish", {"summary": "wrote alpha and beta"}, 0, "f")
            return
        if kind == "worker":
            if not has_tool:
                title = "alpha" if "alpha.txt" in str(messages) else "beta"
                yield chunk_tool("write_file", {"path": f"{title}.txt", "content": title.upper()}, 0, "w")
                return
            yield chunk_text("created")
            return
        yield chunk_text("child done")


def test_parallel_workers(tmp_path):
    async def go() -> Run:
        settings = Settings(
            workspace=str(tmp_path),
            max_agent_steps=6,
            max_orchestrator_rounds=4,
            model="fake",
            max_concurrent=8,
        )
        bus = EventBus()
        engine = Engine(settings, bus, builtin_tools())
        engine.client = FakeClient()  # type: ignore[assignment]
        run = await engine.create_run("make two files")
        assert run.task is not None
        await run.task
        return run, bus

    run, bus = asyncio.run(go())
    assert run.status == "done"
    assert "alpha" in run.result
    assert len(run.agents) == 2
    assert (tmp_path / "alpha.txt").read_text(encoding="utf-8") == "ALPHA"
    assert (tmp_path / "beta.txt").read_text(encoding="utf-8") == "BETA"


def test_usage_events_emitted(tmp_path):
    async def go() -> list[dict]:
        settings = Settings(workspace=str(tmp_path), max_agent_steps=4, max_orchestrator_rounds=3, model="fake")
        bus = EventBus()
        events: list[dict] = []
        async def collect() -> None:
            queue = await bus.subscribe()
            for _ in range(200):
                events.append(await queue.get())
        engine = Engine(settings, bus, builtin_tools())
        engine.client = FakeClient()  # type: ignore[assignment]
        collector = asyncio.create_task(collect())
        run = await engine.create_run("make two files")
        assert run.task is not None
        await run.task
        collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        return events

    events = asyncio.run(go())
    kinds = {e["type"] for e in events}
    assert "run.usage" in kinds
    assert "agent.usage" in kinds
    for e in events:
        if e["type"] in {"run.usage", "agent.usage"}:
            assert e["num_ctx"] > 0
            assert e["prompt_tokens"] > 0


def test_depth_limit(tmp_path):
    async def go() -> Run:
        settings = Settings(workspace=str(tmp_path), max_agent_steps=4, max_orchestrator_rounds=3, model="fake")
        engine = Engine(settings, EventBus(), builtin_tools())

        class DepthClient:
            async def stream_chat(self, **kwargs: Any):
                messages = kwargs.get("messages") or []
                blob = "\n".join(str(m.get("content") or "") for m in messages)
                if "orchestrator" in str(messages[0].get("content") or ""):
                    if any(m.get("role") == "tool" for m in messages):
                        yield chunk_tool("finish", {"summary": "ok"})
                    else:
                        yield chunk_tool("spawn_task", {"title": "p", "goal": "spawn a child that writes z.txt"})
                    return
                if "Depth: 1/" in blob and not any(m.get("role") == "tool" for m in messages):
                    yield chunk_tool("spawn_subagent", {"title": "c", "goal": "write z.txt with Z"})
                    return
                if "Depth: 2/" in blob and not any(m.get("role") == "tool" for m in messages):
                    yield chunk_tool("write_file", {"path": "z.txt", "content": "Z"})
                    return
                yield chunk_text("done")

        engine.client = DepthClient()  # type: ignore[assignment]
        run = await engine.create_run("nested")
        assert run.task is not None
        await run.task
        return run

    run = asyncio.run(go())
    assert run.status == "done"
    depths = sorted(a.depth for a in run.agents.values())
    assert depths == [1, 2]
    assert (tmp_path / "z.txt").read_text(encoding="utf-8") == "Z"
