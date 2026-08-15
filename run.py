from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def iron_health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=1.2) as res:
            body = res.read().decode("utf-8", errors="replace")
        return '"name":"iron"' in body.replace(" ", "")
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def free_port(host: str, start: int) -> int | None:
    for port in range(start, start + 30):
        if not port_open(host, port):
            return port
    return None


def ensure_frontend() -> None:
    dist_index = ROOT / "frontend" / "dist" / "index.html"
    if dist_index.exists():
        src_dirs = [ROOT / "frontend" / "src", ROOT / "frontend"]
        newest = dist_index.stat().st_mtime
        stale = False
        for folder in src_dirs:
            if not folder.exists():
                continue
            for base, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d not in {"node_modules", "dist"} and not d.startswith(".")]
                for f in files:
                    p = Path(base) / f
                    if p.stat().st_mtime > newest:
                        stale = True
                        break
                if stale:
                    break
            if stale:
                break
        if not stale:
            return
    print("building frontend…")
    subprocess.check_call(["npm", "install"], cwd=str(ROOT / "frontend"), shell=os.name == "nt")
    subprocess.check_call(["npm", "run", "build"], cwd=str(ROOT / "frontend"), shell=os.name == "nt")


def start_server(host: str, port: int, stop: threading.Event | None = None) -> None:
    import uvicorn

    config = uvicorn.Config(
        "backend.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="warning",
        reload=False,
    )
    server = uvicorn.Server(config)
    if stop is not None:
        def watcher() -> None:
            stop.wait()
            server.should_exit = True

        threading.Thread(target=watcher, daemon=True).start()
    server.run()


def supervise(host: str, port: int) -> None:
    backoff = 1.0
    while True:
        stop = threading.Event()
        t = threading.Thread(target=start_server, args=(host, port, stop), daemon=True)
        t.start()
        if not wait_ready(host, port, seconds=15):
            print(f"iron: waiting for {host}:{port} ({backoff:.0f}s)", file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 1.7, 20)
            continue
        backoff = 1.0
        # healthy — watch
        fails = 0
        while True:
            if not t.is_alive():
                break
            if iron_health(f"http://{host}:{port}"):
                fails = 0
            else:
                fails += 1
                if fails >= 3:
                    break
            time.sleep(2)
        print(f"iron: restarting {host}:{port} …", file=sys.stderr)
        stop.set()
        t.join(timeout=5)
        time.sleep(backoff)
        backoff = min(backoff * 1.7, 20)


def wait_ready(host: str, port: int, seconds: float = 12.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if iron_health(f"http://{host}:{port}"):
            return True
        time.sleep(0.12)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(prog="iron")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7744)
    parser.add_argument("--dev", action="store_true", help="vite + uvicorn reload")
    parser.add_argument("--web", action="store_true", help="open in a browser instead of the desktop window")
    parser.add_argument("--no-open", action="store_true", help="server only")
    args = parser.parse_args()

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    if args.dev:
        fe = subprocess.Popen(["npm", "run", "dev"], cwd=str(ROOT / "frontend"), shell=os.name == "nt")
        try:
            import uvicorn

            uvicorn.run("backend.app:create_app", factory=True, host=args.host, port=args.port, reload=True)
        finally:
            fe.terminate()
        return

    ensure_frontend()
    host, port = args.host, args.port
    url = f"http://{host}:{port}"
    owned = False

    if port_open(host, port) and not iron_health(url):
        found = free_port(host, port + 1)
        if found is None:
            print(f"iron: no free port near {port} — is something occupying the range?", file=sys.stderr)
            sys.exit(1)
        port = found
        url = f"http://{host}:{port}"

    if not port_open(host, port):
        owned = True
        threading.Thread(target=supervise, args=(host, port), daemon=True).start()
        if not wait_ready(host, port, seconds=15):
            print(f"iron failed to start on {url}", file=sys.stderr)
            sys.exit(1)

    if args.no_open:
        if owned:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return
        return

    if args.web:
        webbrowser.open(url)
        if owned:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return
        return

    from desktop import open_window

    open_window(url)
    if owned:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
