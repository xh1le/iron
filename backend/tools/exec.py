from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from . import proc

MAX_OUTPUT = 24_000


async def run_python(code: str, timeout: int = 30, cwd: str | None = None, cancel: asyncio.Event | None = None) -> str:
    fd, name = tempfile.mkstemp(prefix="iron_", suffix=".py")
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(code, encoding="utf-8")
        t = max(1, min(int(timeout), 300))
        rc, raw, note = await proc.capture(
            ["python", str(path)],
            cwd=cwd,
            env=os.environ.copy(),
            timeout=t,
            cap=MAX_OUTPUT,
            shell=False,
            cancel=cancel,
        )
        text = (raw or b"").decode("utf-8", errors="replace")
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n… [truncated]"
        if note:
            return f"{note}\n{text}".rstrip()
        return f"exit {rc}\n{text}".rstrip()
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
