from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


class Bridge:
    def __init__(self) -> None:
        self.window: Any = None

    def minimize(self) -> None:
        if self.window:
            self.window.minimize()

    def toggle_max(self) -> None:
        if not self.window:
            return
        if getattr(self.window, "maximized", False):
            self.window.restore()
            return
        try:
            self.window.maximize()
        except Exception:
            self.window.toggle_fullscreen()

    def close(self) -> None:
        if self.window:
            self.window.destroy()


def _edge_chrome() -> str | None:
    env = os.environ.get("IRON_BROWSER")
    if env and Path(env).exists():
        return env
    named = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        shutil.which("chromium"),
    ]
    paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Microsoft\WindowsApps\msedge.exe"),
    ]
    for item in named + paths:
        if item and Path(item).exists():
            return item
    return None


def _app_user_data() -> Path:
    data = Path.home() / ".iron" / "app-profile"
    data.mkdir(parents=True, exist_ok=True)
    return data


def open_window(url: str) -> None:
    browser = _edge_chrome()
    if browser:
        profile = _app_user_data()
        cmd = [
            browser,
            f"--app={url}",
            "--window-size=1440,920",
            "--window-position=80,40",
            f"--user-data-dir={profile}",
            "--class=iron",
        ]
        subprocess.run(cmd, check=False)
        sys.exit(0)

    try:
        import webview
    except Exception:
        webbrowser.open(url)
        return

    bridge = Bridge()
    window = webview.create_window(
        title="iron",
        url=url,
        width=1440,
        height=920,
        min_size=(1080, 700),
        background_color="#0b0d10",
        text_select=True,
        js_api=bridge,
        easy_drag=False,
        frameless=False,
    )
    bridge.window = window
    webview.start(debug=False, private_mode=False, gui=None)
    sys.exit(0)
