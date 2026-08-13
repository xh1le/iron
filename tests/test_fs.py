from pathlib import Path

from backend.tools import fs


def test_edit_roundtrip(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("hello world", encoding="utf-8")
    msg = fs.edit_file(str(tmp_path), "a.txt", "world", "iron")
    assert "edited" in msg
    assert p.read_text(encoding="utf-8") == "hello iron"


def test_search(tmp_path: Path):
    (tmp_path / "b.py").write_text("def iron():\n    return 1\n", encoding="utf-8")
    out = fs.search_text(str(tmp_path), "def iron")
    assert "b.py:1:" in out
