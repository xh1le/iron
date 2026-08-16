import asyncio
from pathlib import Path

from backend.store import Store


def test_project_chat_upload(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    assert store.projects()
    home = store.projects()[0]
    extra = store.create_project("alpha", str(tmp_path / "ws"))
    assert extra["name"] == "alpha"
    chat = store.create_chat(home["id"], "New chat")
    store.add_message(chat["id"], {"role": "user", "content": "hello there"})
    again = store.chat(chat["id"])
    assert again
    assert again["title"].startswith("hello")
    saved = store.save_upload(chat["id"], "note.txt", b"iron")
    assert Path(saved["path"]).read_text(encoding="utf-8") == "iron"
    assert store.delete_chat(chat["id"]) is True
    assert store.chat(chat["id"]) is None


def test_clear_messages(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    chat = store.create_chat(store.projects()[0]["id"], "New chat")
    store.add_message(chat["id"], {"role": "user", "content": "a"})
    store.add_message(chat["id"], {"role": "assistant", "content": "b"})
    assert store.clear_messages(chat["id"]) is not None
    assert store.chat(chat["id"])["messages"] == []


def test_compact_messages(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    chat = store.create_chat(store.projects()[0]["id"], "New chat")
    for i in range(10):
        store.add_message(chat["id"], {"role": "user", "content": f"msg {i}"})
    out = store.compact_messages(chat["id"], keep=3)
    assert out is not None
    assert [m["content"] for m in out["messages"]] == ["msg 7", "msg 8", "msg 9"]


def test_engine_compact_chat(tmp_path: Path, monkeypatch):
    from backend.config import Settings
    from backend.events import EventBus
    from backend.orchestrator import Engine
    from backend.tools.registry import builtin_tools

    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    chat = store.create_chat(store.projects()[0]["id"], "New chat")
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        store.add_message(chat["id"], {"role": role, "content": f"msg {i}"})

    async def go():
        engine = Engine(Settings(workspace=str(tmp_path), model="fake"), EventBus(), builtin_tools(), store=store)

        async def fake_compact(model, user):
            assert "Existing memory" not in user
            assert "msg 0" in user and "msg 6" in user
            assert "msg 7" not in user
            return "COMPACTED BLOCK"

        engine._call_compact = fake_compact  # type: ignore[method-assign]
        res = await engine.compact_chat(chat["id"], keep=3)
        assert res and res.get("ok") is True
        assert res["dropped"] == 7
        updated = store.chat(chat["id"])
        assert len(updated["messages"]) == 4
        assert updated["messages"][-1]["role"] == "system"
        assert "context compacted" in updated["messages"][-1]["content"]
        assert updated["memory"]["summary"] == "COMPACTED BLOCK"
        # second pass merges existing memory
        async def fake_compact2(model, user):
            assert "Existing memory" in user and "COMPACTED BLOCK" in user
            return "MERGED"

        engine._call_compact = fake_compact2  # type: ignore[method-assign]
        res2 = await engine.compact_chat(chat["id"], keep=3)
        assert res2 and res2.get("ok") is True
        assert res2["dropped"] == 1
        assert store.chat(chat["id"])["memory"]["summary"] == "MERGED"

    asyncio.run(go())


def test_edit_delete_message(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    chat = store.create_chat(store.projects()[0]["id"], "New chat")
    store.add_message(chat["id"], {"role": "user", "content": "hi there"})
    mid = store.chat(chat["id"])["messages"][0]["id"]
    assert store.edit_message(chat["id"], mid, "changed") is not None
    assert store.chat(chat["id"])["messages"][0]["content"] == "changed"
    assert store.delete_message(chat["id"], mid) is not None
    assert store.chat(chat["id"])["messages"] == []


def test_project_memory_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    pid = store.projects()[0]["id"]
    store.memory_put(pid, "api", "POST /api/runs", run_id="run_1")
    store.memory_put_batch(pid, {"file": "src/app.py", "dep": "fastapi"}, run_id="run_1")
    assert store.memory_get(pid, "api") == "POST /api/runs"
    all_mem = store.memory_all(pid)
    assert all_mem["file"] == "src/app.py"
    assert all_mem["dep"] == "fastapi"
    assert store.memory_all("nope") == {}
    reopened = Store()
    assert reopened.memory_get(pid, "api") == "POST /api/runs"


def test_chat_memory_and_finish_run_usage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    store = Store()
    chat = store.create_chat(store.projects()[0]["id"], "New chat")
    assert chat["memory"] == {"summary": "", "updated_at": 0}
    store.update_chat_memory(chat["id"], "decided to use fastapi")
    assert store.chat(chat["id"])["memory"]["summary"] == "decided to use fastapi"
    store.add_message(chat["id"], {"role": "user", "content": "q"})
    store.add_message(chat["id"], {"role": "assistant", "content": "", "run_id": "run_x"})
    store.finish_run("run_x", "answer", "done", usage={"prompt": 1234, "ctx": 65536})
    msg = store.chat(chat["id"])["messages"][1]
    assert msg["usage"] == {"prompt": 1234, "ctx": 65536}
    assert msg["content"] == "answer"