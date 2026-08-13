from __future__ import annotations

import asyncio
import os
from pathlib import Path

MAX_OUTPUT = 24_000
TIMEOUT_DEFAULT = 60


async def run_shell(root: str, command: str, timeout: int = TIMEOUT_DEFAULT) -> str:
    cwd = Path(root).expanduser().resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=max(5, int(timeout)))
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"[timeout after {timeout}s]\ncommand: {command}"
    except OSError as exc:
        return f"[spawn failed] {exc}"
    text = (raw or b"").decode("utf-8", errors="replace")
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n… [truncated]"
    code = proc.returncode
    return f"$ {command}\nexit {code}\n{text}".rstrip()
