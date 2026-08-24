import backend.tools.web as web

DDG_HTML = """
<html><body>
<div class="result">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs&amp;rut=abc">Example &amp; Docs</a>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=...">The <b>example</b> documentation page.</a>
</div>
<div class="result">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fother.org%2Fapi">Other API</a>
  <a class="result__snippet" href="...">Second result snippet here.</a>
</div>
</body></html>
"""

PAGE_HTML = """
<html><head><title>ignored</title><style>p{color:red}</style></head>
<body>
<script>var x = 1;</script>
<h1>Hello World</h1>
<p>This is   a   page with   text.</p>
<pre>code stays?  yes</pre>
</body></html>
"""


def test_clean_text_strips_tags_and_scripts(monkeypatch):
    text = web._clean_text(PAGE_HTML)
    assert "Hello World" in text
    assert "This is a page with text." in text
    assert "var x" not in text
    assert "p{color:red}" not in text


def test_href_unescape():
    assert web._href_unescape("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs&rut=1") == "https://example.com/docs"
    assert web._href_unescape("https://plain.example/x") == "https://plain.example/x"


def test_web_search_parses_ddg(monkeypatch):
    monkeypatch.setattr(web, "_get", lambda url: DDG_HTML)
    out = web.web_search("example docs")
    assert "1. Example & Docs" in out
    assert "https://example.com/docs" in out
    assert "The example documentation page." in out
    assert "2. Other API" in out


def test_web_search_empty_query():
    assert web.web_search("  ") == "web_search: query required"


def test_web_search_no_results(monkeypatch):
    monkeypatch.setattr(web, "_get", lambda url: "<html></html>")
    assert "no results" in web.web_search("zzz")


def test_web_fetch_returns_readable_text(monkeypatch):
    monkeypatch.setattr(web, "_get", lambda url: PAGE_HTML)
    out = web.web_fetch("https://example.com/page")
    assert "Hello World" in out
    assert "<p>" not in out


def test_web_fetch_rejects_bad_url():
    assert web.web_fetch("ftp://x") == "web_fetch: url must start with http:// or https://"


def test_web_fetch_error(monkeypatch):
    def boom(url):
        raise TimeoutError("timed out")

    monkeypatch.setattr(web, "_get", boom)
    assert "web_fetch failed" in web.web_fetch("https://example.com/x")
