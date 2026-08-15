from __future__ import annotations

import asyncio
import os
from pathlib import Path

from . import proc

MAX_OUTPUT = 24_000
TIMEOUT_DEFAULT = 60


async def run_shell(root: str, command: str, timeout: int = TIMEOUT_DEFAULT, cancel: asyncio.Event | None = None) -> str:
    cwd = Path(root).expanduser().resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    t = max(1, min(int(timeout), 300))
    rc, raw, note = await proc.capture(
        command,
        cwd=str(cwd),
        env=env,
        timeout=t,
        cap=MAX_OUTPUT,
        shell=True,
        cancel=cancel,
    )
    text = (raw or b"").decode("utf-8", errors="replace")
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n… [truncated]"
    if note:
        return f"$ {command}\n{note}\n{text}".rstrip()
    return f"$ {command}\nexit {rc}\n{text}".rstrip()
