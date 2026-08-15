from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

MAX_OUTPUT = 24_000


async def run_python(code: str, timeout: int = 30, cwd: str | None = None) -> str:
    fd, name = tempfile.mkstemp(prefix="iron_", suffix=".py")
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(code, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                str(path),
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return f"[spawn failed] {exc}"
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=max(5, int(timeout)))
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"[timeout after {timeout}s]"
        text = (raw or b"").decode("utf-8", errors="replace")
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n… [truncated]"
        return f"exit {proc.returncode}\n{text}".rstrip()
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
