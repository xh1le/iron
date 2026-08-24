from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) iron-agent/0.1"
TIMEOUT = 12
MAX_FETCH = 40_000
MAX_FETCH_OUT = 8_000
MAX_RESULTS = 6

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        data = res.read(MAX_FETCH)
    return data.decode("utf-8", errors="replace")


def _clean_text(raw: str) -> str:
    text = _SCRIPT_RE.sub(" ", raw or "")
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n", text)
    return text.strip()


def _href_unescape(href: str) -> str:
    """DDG wraps result URLs; keep the real target when present."""
    if "uddg=" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        if q.get("uddg"):
            return q["uddg"][0]
    return href


def web_search(query: str, max_results: int = MAX_RESULTS) -> str:
    """Search the web via DuckDuckGo's HTML endpoint (no API key)."""
    query = (query or "").strip()
    if not query:
        return "web_search: query required"
    max_results = max(1, min(int(max_results), 10))
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        raw = _get(url)
    except Exception as exc:
        return f"web_search failed: {exc}"
    rows: list[str] = []
    # DDG html layout: <a class="result__a" ...>title</a> ... <a class="result__snippet" ...>snippet</a>
    anchors = re.findall(r'<a[^>]+class="result__a"[^>]*>(.*?)</a>', raw, re.S)
    snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', raw, re.S)
    hrefs = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"', raw)
    for i in range(min(len(anchors), max_results)):
        title = _clean_text(anchors[i])
        if not title:
            continue
        line = f"{i + 1}. {title}"
        if i < len(hrefs) and hrefs[i]:
            line += f"\n   {_href_unescape(html.unescape(hrefs[i]))}"
        if i < len(snippets):
            snip = _clean_text(snippets[i])
            if snip:
                line += f"\n   {snip[:400]}"
        rows.append(line)
    if not rows:
        return "web_search: no results (bot check or empty query)"
    return "\n".join(rows)


def web_fetch(url: str, max_chars: int = MAX_FETCH_OUT) -> str:
    """Fetch a URL and return its readable text content."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "web_fetch: url must start with http:// or https://"
    max_chars = max(500, min(int(max_chars), MAX_FETCH_OUT))
    try:
        raw = _get(url)
    except Exception as exc:
        return f"web_fetch failed: {exc}"
    text = _clean_text(raw)
    if not text:
        return "(page has no readable text — it may be a JS app)"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n… [truncated]"
    return text


def handler_search(args: dict[str, Any], _ctx: Any) -> str:
    try:
        limit = int(args.get("max_results") or MAX_RESULTS)
    except (TypeError, ValueError):
        limit = MAX_RESULTS
    return web_search(str(args.get("query") or ""), limit)


def handler_fetch(args: dict[str, Any], _ctx: Any) -> str:
    try:
        limit = int(args.get("max_chars") or MAX_FETCH_OUT)
    except (TypeError, ValueError):
        limit = MAX_FETCH_OUT
    return web_fetch(str(args.get("url") or ""), limit)
