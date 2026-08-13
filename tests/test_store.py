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