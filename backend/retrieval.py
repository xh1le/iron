from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

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


async def retrieve(
    store: Any,
    client: Any,
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
