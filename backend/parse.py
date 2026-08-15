from __future__ import annotations

import json
import re
import uuid
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


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


def _balanced_json_spans(text: str) -> list[str]:
    """Extract balanced {…} spans so nested arguments parse correctly."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, n):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[i : j + 1])
                    i = j + 1
                    break
        else:
            i += 1
            continue
    return out


def extract_text_tool_calls(text: str, allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """Best-effort parse when a small model writes JSON instead of native tool_calls."""
    raw = (text or "").strip()
    if not raw:
        return []
    blobs: list[str] = []
    blobs.extend(f.strip() for f in _FENCE.findall(raw) if f.strip())
    blobs.append(raw)
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(call: dict[str, Any] | None) -> None:
        if not call:
            return
        name = call["function"]["name"]
        if allowed is not None and name not in allowed:
            return
        key = name + call["function"]["arguments"]
        if key in seen:
            return
        seen.add(key)
        calls.append(call)

    for blob in blobs:
        for span in _balanced_json_spans(blob):
            try:
                data = json.loads(span)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
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
            if calls:
                return calls
    return calls
