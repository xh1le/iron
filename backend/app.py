from __future__ import annotations

import asyncio
import os
import platform
import secrets
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings, merge_settings
from .events import EventBus
from .mcp import normalize_config, validate_server
from .models import ChatIn, ChatPatch, ProjectIn, RunIn, SettingsIn
from .orchestrator import Engine, Run
from .store import Store
from .tools.registry import builtin_tools

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"


def _reveal_in_explorer(path: str) -> None:
    p = Path(path).resolve()
    system = platform.system()
    if system == "Windows":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def create_app() -> FastAPI:
    settings = load_settings()
    bus = EventBus()
    store = Store()
    engine = Engine(settings, bus, builtin_tools(), store=store)
    token = secrets.token_urlsafe(24)
    print(f"iron: local token {token}", file=sys.stderr)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(app.state.settings.workspace).mkdir(parents=True, exist_ok=True)
        current = app.state.settings
        if not current.model:
            try:
                models = await app.state.engine.client.list_models()
            except Exception:
                models = []
            if models:
                preferred = ("gemma4:e4b", "gemma4:12b", "gemma4:e2b")
                names = [m["name"] for m in models]
                pick = next((n for n in preferred if n in names), names[0])
                updated = merge_settings(current, {"model": pick})
                app.state.settings = updated
                app.state.engine.reload(updated)
        yield
        try:
            await app.state.engine.close()
        except Exception:
            pass

    app = FastAPI(title="iron", version="0.1.0", lifespan=lifespan)
    # Same-origin only: the frontend is served by this app (or proxied by vite in dev),
    # so cross-origin requests get no CORS headers and are blocked by the browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            if request.headers.get("X-Iron-Token") != token:
                return JSONResponse({"error": "forbidden — missing local token"}, status_code=403)
        return await call_next(request)

    app.state.settings = settings
    app.state.bus = bus
    app.state.engine = engine
    app.state.store = store
    app.state.token = token

    def persist_run(run: Run) -> None:
        if not run.chat_id:
            return
        store.finish_run(run.id, run.result or run.error, run.status, usage=run.usage_snapshot())
        if run.project_id:
            store.memory_put_batch(run.project_id, run.memory.all(), run.id)
        engine.schedule_summary(run.chat_id, run.project_id)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "name": "iron", "model": app.state.settings.resolved_model()}

    @app.get("/api/bootstrap")
    async def bootstrap() -> dict[str, Any]:
        return {"token": app.state.token}

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        return app.state.settings.model_dump()

    @app.put("/api/settings")
    async def put_settings(body: SettingsIn) -> dict[str, Any]:
        updated = merge_settings(app.state.settings, body.model_dump(exclude_none=True))
        app.state.settings = updated
        app.state.engine.reload(updated)
        return updated.model_dump()

    @app.get("/api/models")
    async def models() -> dict[str, Any]:
        try:
            items = await app.state.engine.client.list_models()
            return {"models": items, "error": None}
        except Exception as exc:
            return {"models": [], "error": str(exc)}

    @app.get("/api/mcp/servers")
    async def mcp_servers() -> dict[str, Any]:
        return {"servers": app.state.engine.mcp.snapshot()}

    @app.post("/api/mcp/servers")
    async def mcp_add(body: dict[str, Any]) -> dict[str, Any]:
        name = str(body.get("name") or "").strip()
        cfg = normalize_config(dict(body.get("config") or {}))
        error = validate_server(name, cfg)
        if error:
            return {"ok": False, "error": error}
        servers = dict(app.state.settings.mcp_servers)
        if name in servers:
            return {"ok": False, "error": "a server with that name already exists"}
        servers[name] = cfg
        updated = merge_settings(app.state.settings, {"mcp_servers": servers})
        app.state.settings = updated
        app.state.engine.reload(updated)
        return {"ok": True, "servers": app.state.engine.mcp.snapshot()}

    @app.delete("/api/mcp/servers/{name}")
    async def mcp_remove(name: str) -> dict[str, Any]:
        servers = dict(app.state.settings.mcp_servers)
        if name not in servers:
            return {"ok": False, "error": "not found"}
        del servers[name]
        updated = merge_settings(app.state.settings, {"mcp_servers": servers})
        app.state.settings = updated
        app.state.engine.reload(updated)
        return {"ok": True, "servers": app.state.engine.mcp.snapshot()}

    @app.post("/api/mcp/servers/{name}/test")
    async def mcp_test(name: str) -> dict[str, Any]:
        manager = app.state.engine.mcp
        if name not in manager.servers:
            return {"ok": False, "error": "not found"}
        try:
            tools = await asyncio.wait_for(manager.probe(name), timeout=25)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "connection timed out"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "tools": tools}

    @app.get("/api/projects")
    async def list_projects() -> dict[str, Any]:
        return {"projects": store.projects(), "active_project_id": store.snapshot().get("active_project_id")}

    @app.post("/api/projects")
    async def create_project(body: ProjectIn) -> dict[str, Any]:
        return store.create_project(body.name, body.workspace)

    @app.put("/api/projects/{project_id}")
    async def update_project(project_id: str, body: ProjectIn) -> dict[str, Any]:
        item = store.update_project(project_id, body.model_dump())
        return item or {"error": "not found"}

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str) -> dict[str, Any]:
        ok = store.delete_project(project_id)
        return {"ok": ok}

    @app.get("/api/projects/{project_id}/files")
    async def project_files(project_id: str) -> dict[str, Any]:
        proj = store.project(project_id)
        if not proj:
            return {"error": "not found"}
        files = await asyncio.to_thread(store.project_files, project_id)
        return {"files": files, "workspace": proj.get("workspace") or ""}

    @app.post("/api/projects/{project_id}/reveal")
    async def reveal_project(project_id: str) -> dict[str, Any]:
        proj = store.project(project_id)
        if not proj:
            return {"ok": False, "error": "not found"}
        raw = (proj.get("workspace") or "").strip()
        if not raw:
            from .config import default_workspace

            raw = str(default_workspace())
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        try:
            await asyncio.to_thread(_reveal_in_explorer, str(path))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/chats")
    async def list_chats(project_id: str | None = None) -> dict[str, Any]:
        return {"chats": store.chats(project_id)}

    @app.post("/api/chats")
    async def create_chat(body: ChatIn) -> dict[str, Any]:
        try:
            return store.create_chat(body.project_id, body.title)
        except ValueError as exc:
            return {"error": str(exc)}

    @app.get("/api/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        item = store.chat(chat_id)
        return item or {"error": "not found"}

    @app.patch("/api/chats/{chat_id}")
    async def patch_chat(chat_id: str, body: ChatPatch) -> dict[str, Any]:
        item = store.update_chat(chat_id, body.model_dump(exclude_none=True))
        return item or {"error": "not found"}

    @app.delete("/api/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        return {"ok": await asyncio.to_thread(store.delete_chat, chat_id)}

    @app.post("/api/chats/{chat_id}/clear")
    async def clear_chat(chat_id: str) -> dict[str, Any]:
        item = store.clear_messages(chat_id)
        return {"ok": item is not None, "chat": item}

    @app.delete("/api/chats/{chat_id}/messages/{message_id}")
    async def delete_message(chat_id: str, message_id: str) -> dict[str, Any]:
        item = store.delete_message(chat_id, message_id)
        return {"ok": item is not None, "chat": item}

    @app.patch("/api/chats/{chat_id}/messages/{message_id}")
    async def patch_message(chat_id: str, message_id: str, body: dict[str, Any]) -> dict[str, Any]:
        content = str(body.get("content") or "")
        item = store.edit_message(chat_id, message_id, content)
        return {"ok": item is not None, "chat": item}

    @app.post("/api/chats/{chat_id}/upload")
    async def upload(chat_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        if not store.chat(chat_id):
            return {"error": "not found"}
        data = await file.read()
        try:
            return await asyncio.to_thread(store.save_upload, chat_id, file.filename or "file", data)
        except ValueError as exc:
            return {"error": str(exc)}

    @app.get("/api/runs")
    async def list_runs() -> dict[str, Any]:
        return {"runs": [r.model_dump() for r in app.state.engine.recent()]}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = app.state.engine.get(run_id)
        if not run:
            return {"error": "not found"}
        return run.snapshot().model_dump()

    @app.post("/api/runs")
    async def start_run(body: RunIn) -> dict[str, Any]:
        goal = body.goal.strip()
        if not goal:
            return {"error": "goal required"}
        project = store.project(body.project_id) if body.project_id else None
        workspace = body.workspace or (project.get("workspace") if project else "") or app.state.settings.workspace
        chat_id = body.chat_id or ""
        if not chat_id:
            projects = store.projects()
            pid = body.project_id or (projects[0]["id"] if projects else "")
            if not pid:
                return {"error": "no project — create one first"}
            try:
                created = store.create_chat(pid, "New chat")
            except ValueError as exc:
                return {"error": str(exc)}
            chat_id = created["id"]
        elif not store.chat(chat_id):
            return {"error": "chat not found"}
        extra = store.context_block(chat_id, limit=4)
        files = body.attachments or []
        if files:
            listed = "\n".join(f"- {f.get('name')}: {f.get('path')}" for f in files)
            extra = (extra + "\n\nAttached files (already saved, use these paths):\n" + listed).strip()
            goal = goal + "\n\nAttached files:\n" + listed
        store.add_message(
            chat_id,
            {"role": "user", "content": body.goal.strip(), "attachments": files},
        )
        run = await app.state.engine.create_run(
            goal,
            workspace,
            body.model,
            chat_id=chat_id,
            project_id=body.project_id or "",
            extra_context=extra,
            on_done=persist_run,
        )
        store.add_message(chat_id, {"role": "assistant", "content": "", "run_id": run.id})
        snap = run.snapshot().model_dump()
        snap["chat"] = store.chat(chat_id)
        return snap

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        run = app.state.engine.get(run_id)
        if not run:
            return {"error": "not found"}
        run.request_cancel()
        return {"ok": True}

    @app.post("/api/runs/{run_id}/input")
    async def run_input(run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        run = app.state.engine.get(run_id)
        if not run:
            return {"error": "not found"}
        text = str(body.get("text") or "")
        ok = run.provide_input(text)
        if ok and run.chat_id:
            store.add_message(run.chat_id, {"role": "user", "content": text})
        return {"ok": ok}

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if socket.query_params.get("token") != app.state.token:
            await socket.close(code=4401)
            return
        await socket.accept()
        queue = await bus.subscribe()
        try:
            await socket.send_json({"type": "hello", "ok": True})
            while True:
                event = await queue.get()
                await socket.send_text(EventBus.dumps(event))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await bus.unsubscribe(queue)

    if FRONTEND_DIST.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str) -> FileResponse:
            root = FRONTEND_DIST.resolve()
            target = (FRONTEND_DIST / full_path).resolve()
            if full_path and target.is_file() and target.is_relative_to(root):
                return FileResponse(target)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app
