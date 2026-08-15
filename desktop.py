from __future__ import annotations

import shutil
import subprocess
import webbrowser
from pathlib import Path

class Bridge:
    def __init__(self) -> None:
        self.window = None
    def minimize(self) -> None:
        if self.window:
            try: self.window.minimize()
            except Exception: pass
    def toggle_max(self) -> None:
        if not self.window: return
        try:
            if getattr(self.window, "maximized", False): self.window.restore()  # type: ignore
            else: self.window.maximize()  # type: ignore
        except Exception:
            try: self.window.toggle_fullscreen()  # type: ignore
            except Exception: pass
    def close(self) -> None:
        if self.window:
            try: self.window.destroy()  # type: ignore
            except Exception: pass

def _browser_cmd(url: str) -> list[str] | None:
    for name in ("chrome", "msedge", "chromium", "firefox"):
        p = shutil.which(name)
        if p:
            if "firefox" in name:
                return [p, "-new-window", url]
            return [p, f"--app={url}", "--window-size=1440,920"]
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
    ]:
        if Path(p).exists():
            return [p, f"--app={url}"] if "Firefox" not in p else [p, "-new-window", url]
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
