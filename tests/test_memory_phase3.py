import asyncio

from backend.config import Settings
from backend.memory import SharedMemory
from backend.retrieval import Embedder, retrieve
from backend.tools.registry import ToolContext, _read


def test_file_cache_roundtrip():
    mem = SharedMemory()
    key = ("a.txt", 1, 10)
    assert mem.file_cache_get(key) is None
    mem.file_cache_put(key, 123.0, 5, "cached text")
    assert mem.file_cache_get(key) == (123.0, 5, "cached text")


def test_file_cache_evicts_oldest():
    mem = SharedMemory()
    for i in range(mem.MAX_FILES + 5):
        mem.file_cache_put(("f%d" % i, 1, 1), 0.0, 1, "x")
    assert len(mem._files) <= mem.MAX_FILES


def test_read_handler_caches(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello world\n" * 5, encoding="utf-8")
    mem = SharedMemory()
    ctx = ToolContext(str(tmp_path), mem)
    out1 = asyncio.run(_read({"path": "a.txt"}, ctx))
    assert "hello world" in out1
    out2 = asyncio.run(_read({"path": "a.txt"}, ctx))
    assert out1 == out2
    p.write_text("changed content!\n" * 20, encoding="utf-8")
    out3 = asyncio.run(_read({"path": "a.txt"}, ctx))
    assert out3 != out1
    assert "changed content" in out3


class FakeEmbedder:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    async def ensure(self) -> bool:
        return self.available

    async def embed(self, text: str) -> list[float]:
        v = [1.0] * 8 if "api" in text or "run" in text else [0.0] * 8
        return v

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


def test_retrieve_uses_embedder_rerank(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    project = store.projects()[0]
    store.memory_put(project["id"], "api endpoint", "POST /api/runs starts a run on the local server")
    store.memory_put(project["id"], "styling", "the ui uses glassmorphism panels everywhere")
    hits = asyncio.run(retrieve(store, FakeEmbedder(), project["id"], "", "how do I start a run", top_k=3))
    assert hits
    assert "api endpoint" in hits[0]


def test_retrieve_bm25_only_when_embedder_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    project = store.projects()[0]
    store.memory_put(project["id"], "api endpoint", "POST /api/runs starts a run on the local server")
    hits = asyncio.run(retrieve(store, FakeEmbedder(available=False), project["id"], "", "start a run", top_k=3))
    assert any("api endpoint" in h for h in hits)


def test_embedder_probe_and_fetch():
    class FakeClient:
        def __init__(self) -> None:
            self.settings = Settings()

        async def list_models(self):
            return [{"name": "some-model"}, {"name": "nomic-embed-text"}]

    emb = Embedder(FakeClient())
    assert asyncio.run(emb.ensure()) is True
    assert emb.model == "nomic-embed-text"
    assert asyncio.run(emb.ensure()) is True  # cached


def test_embedder_probe_missing_model():
    class FakeClient:
        def __init__(self) -> None:
            self.settings = Settings()

        async def list_models(self):
            return [{"name": "qwen"}]

    emb = Embedder(FakeClient())
    assert asyncio.run(emb.ensure()) is False
    assert emb.model is None
