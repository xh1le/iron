from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from typing import Any

import httpx

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def bm25_scores(docs: list[str], query: str, k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    if not n:
        return []
    q_terms = set(tokenize(query))
    if not q_terms:
        return [0.0] * n
    token_docs = [tokenize(d) for d in docs]
    lengths = [len(t) for t in token_docs]
    avg = sum(lengths) / n or 1.0
    df: Counter[str] = Counter()
    for tokens in token_docs:
        for term in set(tokens):
            df[term] += 1
    idf: dict[str, float] = {}
    for term in q_terms:
        idf[term] = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
    scores: list[float] = []
    for i, tokens in enumerate(token_docs):
        counts = Counter(tokens)
        dl = lengths[i]
        score = 0.0
        for term in q_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            score += idf[term] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg))
        scores.append(score)
    return scores


class Embedder:
    """Lazy embedding client over ollama's /api/embed with an in-memory cache.

    Falls back to nothing (BM25 only) when no embed model is installed.
    """

    PREFERRED = ["nomic-embed-text", "bge-m3", "all-minilm", "mxbai-embed-large"]

    def __init__(self, client: Any, fetch: Any = None) -> None:
        self.client = client
        self.model: str | None = None
        self._lock = asyncio.Lock()
        self._cache: dict[str, list[float]] = {}
        self._fetch = fetch or self._default_fetch

    async def _default_fetch(self, model: str, text: str) -> list[float]:
        url = self.client.settings.ollama_host.rstrip("/") + "/api/embed"
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=60.0)) as http:
            res = await http.post(url, json={"model": model, "input": text})
            res.raise_for_status()
            data = res.json()
        embs = data.get("embeddings")
        if embs:
            return embs[0] if isinstance(embs[0], list) else []
        return data.get("embedding") or []

    async def ensure(self) -> bool:
        if self.model is not None:
            return bool(self.model)
        async with self._lock:
            if self.model is not None:
                return bool(self.model)
            try:
                items = await self.client.list_models()
                names = [str(m.get("name") or "") for m in items]
                self.model = next((n for n in self.PREFERRED if n in names), None)
            except Exception:
                self.model = None
        return bool(self.model)

    async def embed(self, text: str) -> list[float]:
        key = text[:512]
        if key in self._cache:
            return self._cache[key]
        vec = await self._fetch(self.model or "", text)
        self._cache[key] = vec
        return vec

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


async def retrieve(
    store: Any,
    embedder: Any,
    project_id: str,
    chat_id: str,
    query: str,
    top_k: int = 5,
) -> list[str]:
    """Rank project facts and other chats' summaries against `query`.

    BM25 first (cheap, great for code terms); if an embedder is available the
    top candidates are re-ranked with a hybrid BM25 + cosine score.
    """
    if store is None or not project_id:
        return []
    docs: list[str] = []
    labels: list[str] = []

    facts = store.memory_all(project_id) or {}
    for key, value in facts.items():
        line = f"{key}: {value}"
        docs.append(line)
        labels.append("fact")

    chats = store.chats(project_id) or []
    for c in chats:
        if c.get("id") == chat_id:
            continue
        summary = ((c.get("memory") or {}).get("summary") or "").strip()
        if not summary:
            continue
        docs.append(summary)
        labels.append("chat")

    if not docs:
        return []

    scores = bm25_scores(docs, query)
    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)
    order = [i for i in order if scores[i] > 0][:20]
    if not order:
        return []

    if embedder is not None and await embedder.ensure():
        try:
            q_emb = await embedder.embed(query)
            doc_embs = await embedder.embed_many([docs[i] for i in order])
            best = max(scores[i] for i in order) or 1.0
            ranked = sorted(
                order,
                key=lambda i: 0.5 * (scores[i] / best) + 0.5 * _cosine(q_emb, doc_embs[order.index(i)]),
                reverse=True,
            )
            order = ranked
        except Exception:
            pass

    out: list[str] = []
    for i in order[:top_k]:
        if labels[i] == "fact":
            out.append(f"· {docs[i]}")
        else:
            out.append(f"· earlier chat: {docs[i][:400]}")
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)
