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


def _projects_root() -> Path:
    root = Path(__file__).resolve().parent.parent / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_project_workspace(name: str, project_id: str, workspace: str) -> str:
    raw = (workspace or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (_projects_root() / p).resolve()
        else:
            p = p.resolve()
    else:
        safe = SAFE_NAME.sub("_", name.strip().lower())[:40].strip("_") or "untitled"
        folder = f"{safe}-{project_id[4:8]}"
        p = (_projects_root() / folder).resolve()
    p.mkdir(parents=True, exist_ok=True)
    try:
        marker = p / ".iron-project"
        if not marker.exists():
            marker.write_text(project_id, encoding="utf-8")
    except OSError:
        pass
    return str(p)


def _guard_chat_id(chat_id: str) -> None:
    if not chat_id or ".." in chat_id or any(c in chat_id for c in "/\\"):
        raise ValueError("invalid chat id")


class Store:
    """Projects, chats, messages, uploads, and persistent memory on disk."""

    def __init__(self) -> None:
        self.root = iron_home()
        self.path = self.root / "store.json"
        self.uploads = self.root / "uploads"
        self.mem_path = self.root / "memory.json"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data = self._load()
        self._mem = self._load_mem()

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
            for chat in data["chats"]:
                chat.setdefault("memory", {"summary": "", "updated_at": 0})
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

    def _load_mem(self) -> dict[str, Any]:
        if not self.mem_path.exists():
            return {}
        try:
            data = json.loads(self.mem_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            try:
                backup = self.mem_path.with_name(f"memory.json.corrupt-{now_ms()}")
                self.mem_path.replace(backup)
            except OSError:
                pass
            return {}

    def _save_mem(self) -> None:
        tmp = self.mem_path.with_name(f"{self.mem_path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._mem, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.mem_path)

    def memory_put(self, project_id: str, key: str, value: str, run_id: str = "") -> None:
        key = (key or "").strip()
        value = (value or "").strip()[:2000]
        if not key or not value or not project_id:
            return
        with self._lock:
            project = self._mem.setdefault(project_id, {})
            entry = project.setdefault(key, {"value": "", "ts": 0, "runs": []})
            entry["value"] = value
            entry["ts"] = now_ms()
            if run_id and run_id not in entry["runs"]:
                entry["runs"].append(run_id)
                entry["runs"] = entry["runs"][-20:]
            self._save_mem()

    def memory_put_batch(self, project_id: str, items: dict[str, str], run_id: str = "") -> None:
        if not project_id or not items:
            return
        with self._lock:
            project = self._mem.setdefault(project_id, {})
            changed = False
            for key, value in items.items():
                key = (key or "").strip()
                value = (value or "").strip()[:2000]
                if not key or not value:
                    continue
                entry = project.setdefault(key, {"value": "", "ts": 0, "runs": []})
                if entry["value"] != value:
                    entry["value"] = value
                    entry["ts"] = now_ms()
                    changed = True
                if run_id and run_id not in entry["runs"]:
                    entry["runs"].append(run_id)
                    entry["runs"] = entry["runs"][-20:]
                    changed = True
            if changed:
                self._save_mem()

    def memory_get(self, project_id: str, key: str) -> str:
        with self._lock:
            entry = (self._mem.get(project_id) or {}).get(key)
            return (entry or {}).get("value", "") or ""

    def memory_all(self, project_id: str) -> dict[str, str]:
        with self._lock:
            return {k: v.get("value", "") for k, v in (self._mem.get(project_id) or {}).items()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def projects(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._data["projects"])

    def project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((p for p in self._data["projects"] if p["id"] == project_id), None)

    def project_files(self, project_id: str, limit: int = 30) -> list[dict[str, Any]]:
        proj = self.project(project_id)
        if not proj:
            return []
        raw = (proj.get("workspace") or "").strip()
        if not raw:
            try:
                from .config import default_workspace

                raw = str(default_workspace())
            except Exception:
                return []
        path = Path(raw).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            return []
        files: list[dict[str, Any]] = []
        try:
            for p in path.iterdir():
                if p.name == ".iron-project":
                    continue
                try:
                    is_dir = p.is_dir()
                    stat = p.stat()
                except OSError:
                    continue
                files.append(
                    {
                        "name": p.name,
                        "is_dir": is_dir,
                        "size": stat.st_size if not is_dir else 0,
                        "modified": int(stat.st_mtime * 1000),
                    }
                )
                if len(files) >= limit:
                    break
        except OSError:
            return []
        files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return files

    def create_project(self, name: str, workspace: str = "") -> dict[str, Any]:
        project_id = _id("prj")
        clean_name = (name or "untitled").strip()[:80] or "untitled"
        try:
            resolved = _resolve_project_workspace(clean_name, project_id, workspace)
        except Exception:
            # fallback to raw workspace or projects root on failure
            resolved = (workspace or "").strip() or str(_projects_root() / f"untitled-{project_id[4:8]}")
            try:
                Path(resolved).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        item = {
            "id": project_id,
            "name": clean_name,
            "workspace": resolved,
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
                # handle name first so workspace resolve can use new name if needed
                if "name" in patch and patch["name"] is not None:
                    item["name"] = patch["name"]
                if "workspace" in patch and patch["workspace"] is not None:
                    raw = patch["workspace"]
                    if isinstance(raw, str) and raw.strip():
                        try:
                            resolved = _resolve_project_workspace(item.get("name", "untitled"), project_id, raw)
                            item["workspace"] = resolved
                        except Exception:
                            item["workspace"] = raw
                    else:
                        # explicit empty -> keep as-is (allows clearing)
                        item["workspace"] = raw
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
            "memory": {"summary": "", "updated_at": 0},
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

    def update_chat_memory(self, chat_id: str, summary: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                item.setdefault("memory", {"summary": "", "updated_at": 0})
                item["memory"]["summary"] = (summary or "").strip()[:1600]
                item["memory"]["updated_at"] = now_ms()
                self._save()
                return dict(item)
        return None

    def finish_run(self, run_id: str, content: str, status: str, usage: dict[str, int] | None = None) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                for msg in item["messages"]:
                    if msg.get("run_id") == run_id and msg.get("role") == "assistant":
                        msg["content"] = content
                        msg["status"] = status
                        if usage:
                            msg["usage"] = usage
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
                            "usage": usage or {},
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

    def clear_messages(self, chat_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                item["messages"] = []
                item["updated_at"] = now_ms()
                self._save()
                return dict(item)
        return None

    def compact_messages(self, chat_id: str, keep: int = 4) -> dict[str, Any] | None:
        """Drop all but the last `keep` messages (older history moves into memory)."""
        with self._lock:
            for item in self._data["chats"]:
                if item["id"] != chat_id:
                    continue
                msgs = item.get("messages") or []
                if len(msgs) <= keep:
                    return dict(item)
                item["messages"] = msgs[-keep:]
                item["updated_at"] = now_ms()
                self._save()
                return dict(item)
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
