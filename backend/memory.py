from __future__ import annotations

from threading import Lock
from typing import Any


class SharedMemory:
    """Tiny key-value store shared by every agent in a run."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
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
