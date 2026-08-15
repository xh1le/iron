from __future__ import annotations

from typing import Any

CHARS_PER_TOKEN = 3.2


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (chars/3.2) for budget decisions and UI gauges."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def estimate_messages(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += estimate_tokens(content)
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            total += estimate_tokens(fn.get("name") or "") + estimate_tokens(fn.get("arguments") or "")
    return total


def ctx_budget(num_ctx: int, target: float) -> int:
    """Tokens available for the prompt, leaving room for output."""
    num_ctx = max(4096, int(num_ctx))
    target = max(0.1, min(0.95, float(target)))
    reserve = min(2048, int(num_ctx * 0.25))
    return max(1024, int(num_ctx * target) - reserve)


def compact_messages(messages: list[dict[str, Any]], budget_tokens: int) -> int:
    """Drop the oldest turns until the transcript fits the budget.

    Truncates oversized tool results first, then pops oldest messages while
    keeping the system + user head and the recent tail intact. Assistant
    messages are dropped together with the tool results they produced.
    Returns the estimated tokens removed.
    """
    for msg in messages[2:]:
        content = msg.get("content")
        if msg.get("role") == "tool" and isinstance(content, str) and estimate_tokens(content) > 400:
            msg["content"] = content[:1200] + "\n… [compacted]"
    total = estimate_messages(messages)
    removed = 0
    while total > budget_tokens and len(messages) > 6:
        dropped = messages.pop(2)
        dropped_tokens = estimate_messages([dropped])
        total -= dropped_tokens
        removed += dropped_tokens
        if dropped.get("role") == "assistant":
            call_ids = {c.get("id") for c in (dropped.get("tool_calls") or []) if c.get("id")}
            while call_ids and len(messages) > 6 and messages[2].get("role") == "tool":
                m = messages[2]
                if m.get("tool_call_id") not in call_ids:
                    break
                messages.pop(2)
                total -= estimate_messages([m])
    return removed


def dedupe_tool_result(messages: list[dict[str, Any]], tool: str, result: str) -> str:
    """If an identical tool result already appears in the recent transcript,
    return a short pointer instead of re-emitting the whole output."""
    for msg in messages[-20:]:
        if msg.get("role") != "tool":
            continue
        if msg.get("_tool") == tool and msg.get("content") == result:
            return f"[repeated output — identical to an earlier {tool} call, see above]"
    return result


async def build_memory_block(
    store: Any,
    project_id: str,
    chat_id: str,
    query: str,
    budget_tokens: int,
    client: Any = None,
    embedder: Any = None,
) -> str:
    """Build a compact, token-capped memory block for the orchestrator prompt.

    Sections: chat summary (rolling), durable project facts, and retrieved
    memory (BM25, upgraded with embeddings when an embed model is available).
    """
    if store is None or not project_id:
        return ""
    budget_tokens = max(256, int(budget_tokens))
    blocks: list[str] = []
    used = 0

    def add(title: str, text: str, share: float) -> None:
        nonlocal used
        text = (text or "").strip()
        if not text:
            return
        cap = int(budget_tokens * share)
        est = estimate_tokens(text)
        if est > cap:
            text = text[: max(1, int(cap * CHARS_PER_TOKEN))]
            est = estimate_tokens(text)
        if used + est > budget_tokens:
            return
        blocks.append(f"[{title}]\n{text}")
        used += est

    chat = store.chat(chat_id) if chat_id else None
    summary = ((chat or {}).get("memory") or {}).get("summary", "")
    add("MEMORY", summary, 0.3)

    facts = store.memory_all(project_id) or {}
    if facts:
        add("PROJECT MEMORY", "\n".join(f"{k}: {v}" for k, v in facts.items()), 0.35)

    if query:
        try:
            from .retrieval import retrieve

            hits = await retrieve(store, client, embedder, project_id, chat_id, query, top_k=3)
            if hits:
                add("RECALLED", "\n".join(hits), 0.35)
        except Exception:
            pass

    if not blocks:
        return ""
    return "\n\n".join(blocks)
