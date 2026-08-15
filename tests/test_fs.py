from pathlib import Path

import pytest

from backend.tools import fs


def test_edit_roundtrip(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("hello world", encoding="utf-8")
    msg = fs.edit_file(str(tmp_path), "a.txt", "world", "iron")
    assert "edited" in msg
    assert p.read_text(encoding="utf-8") == "hello iron"


def test_edit_rejects_empty_old_string(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    with pytest.raises(fs.WorkspaceError):
        fs.edit_file(str(tmp_path), "a.txt", "", "x")


def test_search(tmp_path: Path):
    (tmp_path / "b.py").write_text("def iron():\n    return 1\n", encoding="utf-8")
    out = fs.search_text(str(tmp_path), "def iron")
    assert "b.py:1:" in out


def test_search_file_scoped_to_file(tmp_path: Path):
    (tmp_path / "b.py").write_text("def iron():\n    return 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("def iron():\n    return 2\n", encoding="utf-8")
    out = fs.search_text(str(tmp_path), "def iron", path="b.py")
    assert "b.py:1:" in out
    assert "c.py" not in out
