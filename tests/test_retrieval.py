import asyncio

from backend.config import Settings
from backend.events import EventBus
from backend.orchestrator import Engine
from backend.retrieval import bm25_scores, retrieve
from backend.tools.registry import builtin_tools


def test_bm25_ranks_relevant_higher():
    docs = [
        "the api endpoint is /api/runs which starts a run on the server",
        "colors of the rainbow include red and blue and green",
        "fastapi serves the dashboard on port 7744",
    ]
    scores = bm25_scores(docs, "how do I start an api run?")
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]


def test_bm25_empty():
    assert bm25_scores([], "anything") == []
    assert bm25_scores(["hello world"], "") == [0.0]


def test_retrieve_finds_facts(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    project = store.projects()[0]
    store.memory_put(project["id"], "api endpoint", "POST /api/runs starts a run on the local server")
    other = store.create_chat(project["id"], "other")
    store.update_chat_memory(other["id"], "we discussed which ports the server should use")
    hits = asyncio.run(retrieve(store, None, project["id"], "", "how do I start a run", top_k=3))
    assert any("api endpoint" in h for h in hits)


def test_retrieve_skips_current_chat_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    project = store.projects()[0]
    chat = store.create_chat(project["id"], "current")
    store.update_chat_memory(chat["id"], "this summary must not be retrieved as another chat")
    hits = asyncio.run(retrieve(store, None, project["id"], chat["id"], "this summary must not", top_k=3))
    assert not any("must not be retrieved" in h for h in hits)


def test_summarize_writes_chat_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    settings = Settings(workspace=str(tmp_path), model="fake")
    engine = Engine(settings, EventBus(), builtin_tools(), store=store)
    project = store.projects()[0]
    chat = store.create_chat(project["id"], "New chat")
    store.add_message(chat["id"], {"role": "user", "content": "hello there"})
    store.add_message(chat["id"], {"role": "assistant", "content": "hi"})

    class FakeSummary:
        async def stream_chat(self, **kwargs):
            yield {"choices": [{"delta": {"content": "DECISIONS: nothing\nFACTS: user said hello"}}]}

    engine.client = FakeSummary()  # type: ignore[assignment]
    asyncio.run(engine._summarize(chat["id"]))
    assert store.chat(chat["id"])["memory"]["summary"] == "DECISIONS: nothing\nFACTS: user said hello"


def test_summarize_skips_when_nothing_new(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    settings = Settings(workspace=str(tmp_path), model="fake")
    engine = Engine(settings, EventBus(), builtin_tools(), store=store)
    project = store.projects()[0]
    chat = store.create_chat(project["id"], "New chat")
    store.add_message(chat["id"], {"role": "user", "content": "old message"})
    store.update_chat_memory(chat["id"], "existing summary")

    class Exploding:
        async def stream_chat(self, **kwargs):
            raise AssertionError("should not be called")

    engine.client = Exploding()  # type: ignore[assignment]
    asyncio.run(engine._summarize(chat["id"]))
    assert store.chat(chat["id"])["memory"]["summary"] == "existing summary"


def test_summarize_falls_back_to_worker_model(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    settings = Settings(workspace=str(tmp_path), model="worker-fake")
    engine = Engine(settings, EventBus(), builtin_tools(), store=store)
    project = store.projects()[0]
    chat = store.create_chat(project["id"], "New chat")
    store.add_message(chat["id"], {"role": "user", "content": "msg"})

    calls = []

    class FakeFallback:
        async def stream_chat(self, **kwargs):
            calls.append(kwargs.get("model"))
            if kwargs.get("model") == "gemma4:e2b":
                raise RuntimeError("model missing")
            yield {"choices": [{"delta": {"content": "fallback summary"}}]}

    engine.client = FakeFallback()  # type: ignore[assignment]
    asyncio.run(engine._summarize(chat["id"]))
    assert calls == ["gemma4:e2b", "worker-fake"]
    assert store.chat(chat["id"])["memory"]["summary"] == "fallback summary"
