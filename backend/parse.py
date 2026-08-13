from __future__ import annotations

import json
import re
import uuid
from typing import Any


_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_CALL = re.compile(
    r"\{[^{}]*\"(?:name|tool)\"\s*:\s*\"([^\"]+)\"[^{}]*\}",
    re.S,
)


def _as_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "call_" + uuid.uuid4().hex[:10],
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _obj_to_call(obj: dict[str, Any]) -> dict[str, Any] | None:
    name = str(obj.get("name") or obj.get("tool") or "")
    if not name:
        return None
    args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            args = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            args = {"_raw": args}
    if not isinstance(args, dict):
        args = {"value": args}
    return _as_call(name, args)


def extract_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """Best-effort parse when a small model writes JSON instead of native tool_calls."""
    raw = (text or "").strip()
    if not raw:
        return []
    blobs: list[str] = []
    fences = _FENCE.findall(raw)
    blobs.extend(fences)
    blobs.append(raw)
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(call: dict[str, Any] | None) -> None:
        if not call:
            return
        key = call["function"]["name"] + call["function"]["arguments"]
        if key in seen:
            return
        seen.add(key)
        calls.append(call)

    for blob in blobs:
        blob = blob.strip()
        if not blob:
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            if "tool_calls" in data and isinstance(data["tool_calls"], list):
                for item in data["tool_calls"]:
                    if isinstance(item, dict):
                        add(_obj_to_call(item.get("function") or item))
            elif "tasks" in data and isinstance(data["tasks"], list):
                for item in data["tasks"]:
                    if isinstance(item, dict):
                        add(_as_call("spawn_task", {"title": item.get("title") or "worker", "goal": item.get("goal") or ""}))
            else:
                add(_obj_to_call(data))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    add(_obj_to_call(item))
        if calls:
            return calls

    for match in _CALL.finditer(raw):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            add(_obj_to_call(obj))
    return calls
