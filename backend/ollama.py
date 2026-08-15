from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import Settings


class ModelError(RuntimeError):
    pass


class OllamaClient:
    """Thin OpenAI-compatible + native Ollama wrapper."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=8.0, read=300.0, write=30.0, pool=8.0)

    async def list_models(self) -> list[dict[str, Any]]:
        url = self.settings.ollama_host.rstrip("/") + "/api/tags"
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                res = await client.get(url)
                res.raise_for_status()
            except httpx.HTTPError as exc:
                raise ModelError(f"cannot reach ollama at {self.settings.ollama_host}: {exc}") from exc
        models = res.json().get("models") or []
        out: list[dict[str, Any]] = []
        for item in models:
            name = item.get("name") or item.get("model") or ""
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "size": item.get("size"),
                    "digest": item.get("digest"),
                    "modified_at": item.get("modified_at"),
                }
            )
        return out

    def _chat_url(self, cloud: bool) -> str:
        if cloud and self.settings.cloud_base_url:
            return self.settings.cloud_base_url.rstrip("/") + "/chat/completions"
        return self.settings.ollama_host.rstrip("/") + "/v1/chat/completions"

    def _headers(self, cloud: bool) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if cloud and self.settings.cloud_api_key:
            headers["Authorization"] = f"Bearer {self.settings.cloud_api_key}"
        return headers

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
        cloud: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": self.settings.temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if not cloud:
            payload["options"] = {"num_ctx": num_ctx or self.settings.ctx()}

        url = self._chat_url(cloud)
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                async with client.stream("POST", url, headers=self._headers(cloud), json=payload) as res:
                    if res.status_code >= 400:
                        body = (await res.aread()).decode("utf-8", errors="replace")
                        raise ModelError(f"model error {res.status_code}: {body[:800]}")
                    saw_chunk = False
                    async for line in res.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            break
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        saw_chunk = True
                        yield chunk
                    if not saw_chunk:
                        raise ModelError("model stream produced no data")
            except httpx.HTTPError as exc:
                raise ModelError(f"model stream failed: {exc}") from exc


def extract_delta(chunk: dict[str, Any]) -> dict[str, Any]:
    """Normalize OpenAI-style stream chunks into content / tool_call / usage deltas."""
    choices = chunk.get("choices") or []
    if not choices:
        usage = chunk.get("usage") or {}
        return {"content": "", "reasoning": "", "tool_calls": [], "usage": usage, "finish": None}
    choice = choices[0]
    delta = choice.get("delta") or {}
    return {
        "content": delta.get("content") or "",
        "reasoning": delta.get("reasoning_content") or delta.get("reasoning") or "",
        "tool_calls": delta.get("tool_calls") or [],
        "usage": chunk.get("usage") or {},
        "finish": choice.get("finish_reason"),
    }


def merge_tool_call_deltas(acc: dict[int, dict[str, Any]], deltas: list[dict[str, Any]]) -> None:
    id_to_idx: dict[str, int] = {}
    for idx, slot in acc.items():
        if slot.get("id"):
            id_to_idx[slot["id"]] = idx
    next_idx = max(acc.keys(), default=-1) + 1
    for item in deltas:
        raw_idx = item.get("index")
        try:
            idx = int(raw_idx) if raw_idx is not None else None
        except (TypeError, ValueError):
            idx = None
        cid = item.get("id")
        if idx is None and cid and cid in id_to_idx:
            idx = id_to_idx[cid]
        elif idx is None:
            idx = next_idx
        if idx in acc:
            slot = acc[idx]
        else:
            slot = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            acc[idx] = slot
        next_idx = max(next_idx, idx + 1)
        if cid:
            slot["id"] = cid
            id_to_idx[cid] = idx
        fn = item.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = slot["function"]["name"] + fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] = slot["function"]["arguments"] + fn["arguments"]


def parse_tool_args(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else {"value": data}
            except json.JSONDecodeError:
                pass
        return {"_raw": raw}
