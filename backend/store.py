from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import iron_home
from .events import now_ms

MAX_UPLOAD = 25 * 1024 * 1024
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _safe(name: str) -> str:
    cleaned = SAFE_NAME.sub("_", Path(name).name).strip("._") or "file"
    return cleaned[:120]


def _guard_chat_id(chat_id: str) -> None:
    if not chat_id or ".." in chat_id or any(c in chat_id for c in "/\\"):
        raise ValueError("invalid chat id")


class Store:
    """Projects, chats, messages, and uploads on disk."""

    def __init__(self) -> None:
        self.root = iron_home()
        self.path = self.root / "store.json"
        self.uploads = self.root / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data = self._load()

    def _blank(self) -> dict[str, Any]:
        ts = now_ms()
        project = {
            "id": _id("prj"),
            "name": "home",
            "workspace": "",
            "created_at": ts,
            "updated_at": ts,
        }
        return {"projects": [project], "chats": [], "active_project_id": project["id"]}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = self._blank()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not data.get("projects"):
                blank = self._blank()
                data["projects"] = blank["projects"]
                data.setdefault("active_project_id", blank["active_project_id"])
            data.setdefault("chats", [])
            return data
        except Exception:
            self._backup_corrupt()
            return self._blank()

    def _backup_corrupt(self) -> None:
        try:
            backup = self.path.with_name(f"{self.path.name}.corrupt-{now_ms()}")
            self.path.replace(backup)
        except OSError:
            pass

    def _save(self) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def projects(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._data["projects"])

    def project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((p for p in self._data["projects"] if p["id"] == project_id), None)

    def create_project(self, name: str, workspace: str = "") -> dict[str, Any]:
        item = {
            "id": _id("prj"),
            "name": (name or "untitled").strip()[:80],
            "workspace": workspace,
            "created_at": now_ms(),
            "updated_at": now_ms(),
        }
        with self._lock:
            self._data["projects"].append(item)
            self._data["active_project_id"] = item["id"]
            self._save()
        return item

    def update_project(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["projects"]:
                if item["id"] != project_id:
                    continue
                for key in ("name", "workspace"):
                    if key in patch and patch[key] is not None:
                        item[key] = patch[key]
                item["updated_at"] = now_ms()
                self._save()
                return dict(item)
        return None

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            projects = self._data["projects"]
            if len(projects) <= 1:
                return False
            if not any(p["id"] == project_id for p in projects):
                return False
            removed_chats = [c["id"] for c in self._data["chats"] if c.get("project_id") == project_id]
            self._data["projects"] = [p for p in projects if p["id"] != project_id]
            self._data["chats"] = [c for c in self._data["chats"] if c.get("project_id") != project_id]
            if self._data.get("active_project_id") == project_id:
                self._data["active_project_id"] = self._data["projects"][0]["id"]
            self._save()
        for chat_id in removed_chats:
            folder = self.uploads / chat_id
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
        return True

    def chats(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._data["chats"])
        if project_id:
            items = [c for c in items if c.get("project_id") == project_id]
        items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
        return items

    def chat(self, chat_id: str) -> dict[str, Any] | None:
        with self._lock:
            found = next((c for c in self._data["chats"] if c["id"] == chat_id), None)
            return dict(found) if found else None

    def create_chat(self, project_id: str, title: str = "New chat") -> dict[str, Any]:
        item = {
            "id": _id("cht"),
            "project_id": project_id,
            "title": (title or "New chat").strip()[:80],
            "pinned": False,
            "created_at": now_ms(),
            "updated_at": now_ms(),
            "messages": [],
        }
        with self._lock:
            if not any(p["id"] == project_id for p in self._data["projects"]):
                raise ValueError("project not found")
            self._data["chats"].insert(0, item)
            self._save()
        return item

    def update_chat(self, chat_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                for key in ("title", "pinned", "project_id"):
                    if key in patch and patch[key] is not None:
                        item[key] = patch[key]
                item["updated_at"] = now_ms()
                self._save()
                return dict(item)
        return None

    def delete_chat(self, chat_id: str) -> bool:
        with self._lock:
            before = len(self._data["chats"])
            self._data["chats"] = [c for c in self._data["chats"] if c["id"] != chat_id]
            if len(self._data["chats"]) == before:
                return False
            self._save()
        folder = self.uploads / chat_id
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return True

    def add_message(self, chat_id: str, message: dict[str, Any]) -> dict[str, Any] | None:
        msg = {
            "id": message.get("id") or _id("msg"),
            "role": message.get("role") or "user",
            "content": message.get("content") or "",
            "attachments": message.get("attachments") or [],
            "run_id": message.get("run_id"),
            "ts": message.get("ts") or now_ms(),
        }
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                item["messages"].append(msg)
                if item["title"] in {"", "New chat"} and msg["role"] == "user" and msg["content"]:
                    item["title"] = msg["content"].strip().splitlines()[0][:64]
                item["updated_at"] = now_ms()
                self._save()
                return dict(item)
        return None

    def attach_run(self, chat_id: str, message_id: str, run_id: str) -> None:
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                for msg in item["messages"]:
                    if msg["id"] == message_id:
                        msg["run_id"] = run_id
                item["updated_at"] = now_ms()
                self._save()
                return

    def finish_run(self, run_id: str, content: str, status: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                for msg in item["messages"]:
                    if msg.get("run_id") == run_id and msg.get("role") == "assistant":
                        msg["content"] = content
                        msg["status"] = status
                        item["updated_at"] = now_ms()
                        self._save()
                        return dict(item)
            for item in self._data["chats"]:
                if any(m.get("run_id") == run_id for m in item["messages"]):
                    item["messages"].append(
                        {
                            "id": _id("msg"),
                            "role": "assistant",
                            "content": content,
                            "attachments": [],
                            "run_id": run_id,
                            "status": status,
                            "ts": now_ms(),
                        }
                    )
                    item["updated_at"] = now_ms()
                    self._save()
                    return dict(item)
        return None

    def delete_message(self, chat_id: str, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                before = len(item["messages"])
                item["messages"] = [m for m in item["messages"] if m["id"] != message_id]
                if len(item["messages"]) == before:
                    return None
                item["updated_at"] = now_ms()
                self._save()
                return dict(item)
        return None

    def edit_message(self, chat_id: str, message_id: str, content: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                for msg in item["messages"]:
                    if msg["id"] == message_id and msg.get("role") == "user":
                        msg["content"] = content
                        item["updated_at"] = now_ms()
                        self._save()
                        return dict(item)
                return None
        return None

    def save_upload(self, chat_id: str, filename: str, data: bytes) -> dict[str, Any]:
        _guard_chat_id(chat_id)
        if len(data) > MAX_UPLOAD:
            raise ValueError("file too large (25MB max)")
        folder = self.uploads / chat_id
        folder.mkdir(parents=True, exist_ok=True)
        name = _safe(filename)
        target = folder / name
        n = 1
        while target.exists():
            target = folder / f"{target.stem}_{n}{target.suffix}"
            n += 1
        target.write_bytes(data)
        return {
            "name": target.name,
            "path": str(target),
            "size": len(data),
        }

    def upload_dir(self, chat_id: str) -> Path:
        _guard_chat_id(chat_id)
        path = self.uploads / chat_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def context_block(self, chat_id: str, limit: int = 8) -> str:
        chat = self.chat(chat_id)
        if not chat:
            return ""
        rows: list[str] = []
        for msg in chat.get("messages", [])[-limit:]:
            role = msg.get("role")
            body = (msg.get("content") or "").strip()
            if not body:
                continue
            if role == "user":
                rows.append(f"User: {body[:1200]}")
            elif role == "assistant":
                rows.append(f"Iron: {body[:1200]}")
        return "\n".join(rows)
