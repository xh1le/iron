from __future__ import annotations

from threading import Lock
from typing import Any


class SharedMemory:
    """Tiny key-value store shared by every agent in a run, plus a
    per-run file-read cache that lets repeated reads of unchanged files
    avoid disk I/O (and lets identical reads collapse in the transcript)."""

    MAX_FILES = 64

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._files: dict[Any, tuple[float, int, str]] = {}
        self._lock = Lock()

    def put(self, key: str, value: str) -> None:
        key = (key or "").strip()
        if not key:
            return
        with self._lock:
            self._data[key] = value

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data.get(key)

    def all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data)

    def snapshot(self) -> dict[str, Any]:
        return self.all()

    def file_cache_get(self, key: Any) -> tuple[float, int, str] | None:
        with self._lock:
            return self._files.get(key)

    def file_cache_put(self, key: Any, mtime: float, size: int, text: str) -> None:
        with self._lock:
            self._files[key] = (mtime, size, text)
            if len(self._files) > self.MAX_FILES:
                for old in list(self._files)[: self.MAX_FILES // 4]:
                    del self._files[old]
