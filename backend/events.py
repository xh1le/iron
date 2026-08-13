from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any


def now_ms() -> int:
    return int(time.time() * 1000)


class EventBus:
    """Fan-out bus: every websocket subscriber gets every event, plus a replay buffer per run."""

    def __init__(self, replay: int = 400) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self._replay: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=replay))
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        async with self._lock:
            self._subs.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subs.discard(queue)

    async def emit(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", now_ms())
        run_id = event.get("run_id")
        if run_id:
            self._replay[str(run_id)].append(event)
        async with self._lock:
            targets = list(self._subs)
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def replay(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._replay.get(run_id, ()))

    @staticmethod
    def dumps(event: dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False, default=str)
