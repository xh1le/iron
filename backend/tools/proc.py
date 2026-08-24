from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import threading
import time


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and its whole tree (cmd.exe / python + grandchildren)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=5)
            return
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_sync(
    argv: list[str] | str,
    *,
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: int,
    cap: int,
    shell: bool,
    cancel_event: threading.Event,
    result: dict[str, object],
) -> None:
    """Blocking runner executed on a worker thread. Never touches the event loop."""
    try:
        kwargs = dict(
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        if shell:
            proc = subprocess.Popen(argv, shell=True, **kwargs)
        else:
            proc = subprocess.Popen(argv, **kwargs)
    except OSError as exc:
        result["rc"] = None
        result["data"] = None
        result["note"] = f"[spawn failed] {exc}"
        return

    result["proc"] = proc
    out = bytearray()
    overflow = False
    note: str | None = None
    timed_out = False

    def killer() -> None:
        nonlocal timed_out
        timed_out = True
        _kill_tree(proc)

    timer = threading.Timer(max(0.1, timeout), killer)
    timer.start()
    try:
        while True:
            if cancel_event.is_set():
                note = "[cancelled]"
                _kill_tree(proc)
                break
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            room = cap - len(out)
            if room <= 0 or len(chunk) > room:
                if room > 0:
                    out.extend(chunk[:room])
                overflow = True
                note = "[output too large — truncated]"
                _kill_tree(proc)
                break
            out.extend(chunk)
    finally:
        timer.cancel()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    if note is None:
        if timed_out:
            note = f"[timeout after {timeout}s]"
        elif cancel_event.is_set():
            note = "[cancelled]"
        elif overflow:
            note = "[output too large — truncated]"
    result["rc"] = proc.returncode
    result["data"] = bytes(out)
    result["note"] = note


async def capture(
    argv: list[str] | str,
    *,
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: int,
    cap: int,
    shell: bool = False,
    cancel: asyncio.Event | None = None,
) -> tuple[int | None, bytes | None, str | None]:
    """Run a subprocess off the event loop with bounded output, timeout, and cooperative cancel.

    Returns (returncode, output, note) where `note` explains an early stop:
    timeout, cancellation, or output overflow (output is truncated to `cap`).
    """
    cancel_event = threading.Event()
    done_event = threading.Event()
    result: dict[str, object] = {}
    task = asyncio.create_task(
        asyncio.to_thread(_run_sync, argv, cwd=cwd, env=env, timeout=timeout, cap=cap, shell=shell, cancel_event=cancel_event, result=result)
    )

    watcher: threading.Thread | None = None
    if cancel is not None:
        def watch() -> None:
            # Exit when the call finishes; without this the watcher busy-loops
            # forever once the subprocess ends (zombie thread per shell call).
            while not cancel.is_set() and not done_event.is_set():
                time.sleep(0.05)
            if cancel.is_set() and not done_event.is_set():
                cancel_event.set()
                proc = result.get("proc")
                if proc is not None:
                    _kill_tree(proc)  # type: ignore[arg-type]

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()

    try:
        await task
    except asyncio.CancelledError:
        cancel_event.set()
        proc = result.get("proc")
        if proc is not None:
            _kill_tree(proc)  # type: ignore[arg-type]
        await asyncio.gather(task, return_exceptions=True)
        raise
    finally:
        done_event.set()
        if watcher is not None and watcher.is_alive():
            watcher.join(timeout=2)

    return result.get("rc"), result.get("data"), result.get("note")  # type: ignore[return-value]
