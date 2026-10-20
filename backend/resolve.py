"""Model resolution.

A local agent dies the moment its configured model is not installed. This
module keeps iron alive: it checks the configured model against what Ollama
actually has, falls back to a sensible installed model, and returns a short
human-readable note so the UI can explain the switch.
"""

from __future__ import annotations

import re
from typing import Any

# Substrings that mark a model as an embedding model — never a chat model.
_EMBED_HINTS = ("embed", "bge-", "minilm", "mxbai", "gte-", "e5-", "retrieval")

# Models that are good at code, best first. Only used to break ties among
# installed models when the configured one is missing.
_CODER_HINTS = ("coder", "code", "deepseek-coder", "starcoder")

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.I)


def is_embed_model(name: str) -> bool:
    low = (name or "").lower()
    return any(h in low for h in _EMBED_HINTS)


def param_count(name: str) -> float:
    """Rough parameter count from a tag like ``qwen2.5:7b`` -> 7.0."""
    match = _SIZE_RE.search(name or "")
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _tier(name: str) -> int:
    """Lower is better. Code models first, then instruct-tuned, then the rest."""
    low = (name or "").lower()
    if any(h in low for h in _CODER_HINTS):
        return 0
    if "instruct" in low or "chat" in low or "sft" in low:
        return 1
    return 2


def pick_fallback(names: list[str]) -> str:
    """Choose the best installed chat model from a list of model names.

    Returns "" when only embedding models are installed — an embedding model
    cannot answer a prompt, so failing loudly beats a confusing 400.
    """
    candidates = [n for n in names if n and not is_embed_model(n)]
    if not candidates:
        return ""
    return sorted(candidates, key=lambda n: (_tier(n), -param_count(n), n))[0]


def _same_base(a: str, b: str) -> bool:
    return (a or "").split(":")[0].strip().lower() == (b or "").split(":")[0].strip().lower()


async def resolve_model(client: Any, preferred: str) -> tuple[str, str]:
    """Resolve ``preferred`` against the models Ollama actually serves.

    Returns ``(model, note)``. ``note`` is empty when the preferred model was
    available as-is. When Ollama cannot be reached the preferred model is
    returned unchanged — the caller surfaces the connection error later.
    """
    preferred = (preferred or "").strip()
    try:
        items = await client.list_models()
    except Exception as exc:
        return preferred, f"cannot reach ollama: {exc}"
    names = [str(m.get("name") or "") for m in items if m.get("name")]
    if not names:
        return preferred, "no models installed — run `ollama pull <model>`"
    if preferred and preferred in names:
        return preferred, ""
    if preferred:
        # Same base name, different tag ("qwen3.5" -> "qwen3.5:2b").
        match = next((n for n in names if _same_base(n, preferred)), "")
        if match:
            return match, f"model '{preferred}' is tagged '{match}'"
    fallback = pick_fallback(names)
    if not fallback:
        return preferred, "no usable chat model installed"
    if preferred:
        return fallback, f"model '{preferred}' is not installed — using '{fallback}'"
    return fallback, ""
