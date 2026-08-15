from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

MAX_READ = 180_000
MAX_WRITE = 400_000
MAX_SEARCH_HITS = 80
MAX_LIST = 400
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".iron",
    ".next",
    ".cache",
}


class WorkspaceError(ValueError):
    pass


def resolve_workspace(root: str | Path, rel: str) -> Path:
    base = Path(root).expanduser().resolve()
    target = (base / rel).expanduser().resolve() if rel else base
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise WorkspaceError(f"path escapes workspace: {rel}") from exc
    return target


def relpath(root: str | Path, path: Path) -> str:
    base = Path(root).expanduser().resolve()
    try:
        return str(path.resolve().relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_file(root: str, path: str, offset: int = 1, limit: int = 400) -> str:
    target = resolve_workspace(root, path)
    if not target.exists():
        raise WorkspaceError(f"not found: {path}")
    if not target.is_file():
        raise WorkspaceError(f"not a file: {path}")
    if target.stat().st_size > MAX_READ:
        raise WorkspaceError("file too large to read")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ:
        text = text[:MAX_READ] + "\n… [truncated]"
    lines = text.splitlines()
    start = max(1, int(offset))
    if start > len(lines):
        return f"{relpath(root, target)}  lines 0-0/{len(lines)}"
    end = min(len(lines), start - 1 + max(1, int(limit)))
    numbered = [f"{i + 1:>5}| {lines[i]}" for i in range(start - 1, end)]
    header = f"{relpath(root, target)}  lines {start}-{end}/{len(lines)}"
    return header + "\n" + "\n".join(numbered)


def write_file(root: str, path: str, content: str) -> str:
    if len(content) > MAX_WRITE:
        raise WorkspaceError("write too large")
    target = resolve_workspace(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {relpath(root, target)} ({len(content)} bytes, {content.count(chr(10)) + 1} lines)"


def edit_file(root: str, path: str, old: str, new: str, replace_all: bool = False) -> str:
    if not old:
        raise WorkspaceError("old_string must not be empty")
    target = resolve_workspace(root, path)
    if not target.is_file():
        raise WorkspaceError(f"not found: {path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if old == new:
        raise WorkspaceError("old and new are identical")
    count = text.count(old)
    if count == 0:
        raise WorkspaceError("old_string not found — read the file and match exactly")
    if count > 1 and not replace_all:
        raise WorkspaceError(f"old_string matches {count} times — add context or set replace_all")
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    if len(updated) > MAX_WRITE:
        raise WorkspaceError("edit result too large")
    target.write_text(updated, encoding="utf-8")
    kind = "all" if replace_all else "1"
    return f"edited {relpath(root, target)} ({kind}/{count} replacements)"


def list_dir(root: str, path: str = ".", glob: str = "*") -> str:
    target = resolve_workspace(root, path)
    if not target.exists():
        raise WorkspaceError(f"not found: {path}")
    if target.is_file():
        return relpath(root, target)
    rows: list[str] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name in SKIP_DIRS:
            continue
        name = child.name + ("/" if child.is_dir() else "")
        if glob and glob != "*" and not fnmatch.fnmatch(child.name, glob):
            continue
        rows.append(name)
        if len(rows) >= MAX_LIST:
            rows.append("…")
            break
    return f"{relpath(root, target)}/\n" + "\n".join(rows)


def search_text(root: str, query: str, path: str = ".", glob: str = "") -> str:
    target = resolve_workspace(root, path)
    if not query:
        raise WorkspaceError("query required")
    try:
        rx = re.compile(query)
    except re.error:
        rx = re.compile(re.escape(query))
    hits: list[str] = []
    base = Path(root).expanduser().resolve()

    def scan_file(file: Path) -> None:
        if glob and not fnmatch.fnmatch(file.name, glob):
            return
        try:
            if file.stat().st_size > MAX_READ:
                return
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                try:
                    rel = str(file.resolve().relative_to(base)).replace("\\", "/")
                except ValueError:
                    rel = str(file)
                hits.append(f"{rel}:{i}: {line.strip()[:240]}")
                if len(hits) >= MAX_SEARCH_HITS:
                    return

    def walk(folder: Path) -> None:
        if len(hits) >= MAX_SEARCH_HITS:
            return
        try:
            children = list(folder.iterdir())
        except OSError:
            return
        for child in children:
            if len(hits) >= MAX_SEARCH_HITS:
                return
            if child.name in SKIP_DIRS:
                continue
            if child.is_dir() and not child.is_symlink():
                walk(child)
                continue
            if child.is_symlink() and not child.is_file():
                continue
            scan_file(child)

    if target.is_file():
        scan_file(target)
    else:
        walk(target)
    if not hits:
        return "no matches"
    return "\n".join(hits)
