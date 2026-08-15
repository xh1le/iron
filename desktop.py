from __future__ import annotations

import shutil
import subprocess
import webbrowser
from pathlib import Path


def _geometry_args() -> list[str]:
    """Restore the saved window size/position (0 = auto)."""
    try:
        from backend.config import load_settings

        s = load_settings()
    except Exception:
        return []
    args: list[str] = []
    w, h = s.window_w or 1440, s.window_h or 920
    args.append(f"--window-size={w},{h}")
    if s.window_x >= 0 and s.window_y >= 0:
        args.append(f"--window-position={s.window_x},{s.window_y}")
    return args


def _browser_cmd(url: str) -> list[str] | None:
    for name in ("chrome", "msedge", "chromium", "firefox"):
        p = shutil.which(name)
        if p:
            if "firefox" in name:
                return [p, "-new-window", url]
            return [p, f"--app={url}", *_geometry_args()]
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
    ]:
        if Path(p).exists():
            return [p, f"--app={url}", *_geometry_args()] if "Firefox" not in p else [p, "-new-window", url]
    return None


def open_window(url: str) -> None:
    # Stable path: browser --app window. pywebview's WebView2 wrapper hits COM threading + recursion bugs on this machine.
    cmd = _browser_cmd(url)
    if cmd:
        try:
            subprocess.Popen(cmd, close_fds=False)
            return
        except Exception:
            pass
    webbrowser.open(url)
