import asyncio
from typing import Any

from backend.resolve import is_embed_model, param_count, pick_fallback, resolve_model


class FakeOllama:
    def __init__(self, names: list[str] | None = None, error: Exception | None = None) -> None:
        self.names = names or []
        self.error = error

    async def list_models(self) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        return [{"name": n} for n in self.names]


def test_is_embed_model():
    assert is_embed_model("nomic-embed-text:latest")
    assert is_embed_model("bge-m3")
    assert not is_embed_model("qwen3.5:2b")
    assert not is_embed_model("gemma3:12b")


def test_param_count():
    assert param_count("qwen3.5:2b") == 2.0
    assert param_count("llama3.1:8b") == 8.0
    assert param_count("no-size-here") == 0.0


def test_pick_fallback_prefers_code_models():
    names = ["nomic-embed-text:latest", "llama3.2:1b", "qwen2.5-coder:7b", "mistral:7b"]
    assert pick_fallback(names) == "qwen2.5-coder:7b"


def test_pick_fallback_skips_embedding_models():
    names = ["nomic-embed-text:latest", "mxbai-embed-large"]
    # an embedding model cannot chat — no usable fallback
    assert pick_fallback(names) == ""


def test_pick_fallback_prefers_larger_within_tier():
    assert pick_fallback(["mistral:3b", "mistral:7b"]) == "mistral:7b"


def test_resolve_keeps_installed_model():
    client = FakeOllama(["qwen3.5:2b", "llama3.1:8b"])
    model, note = asyncio.run(resolve_model(client, "qwen3.5:2b"))
    assert model == "qwen3.5:2b"
    assert note == ""


def test_resolve_matches_different_tag():
    client = FakeOllama(["qwen3.5:2b"])
    model, note = asyncio.run(resolve_model(client, "qwen3.5"))
    assert model == "qwen3.5:2b"
    assert "tagged" in note


def test_resolve_falls_back_when_missing():
    client = FakeOllama(["qwen3.5:2b", "llama3.1:8b"])
    model, note = asyncio.run(resolve_model(client, "gpt-oss:120b"))
    assert model in {"qwen3.5:2b", "llama3.1:8b"}
    assert "not installed" in note


def test_resolve_reports_no_models():
    client = FakeOllama([])
    model, note = asyncio.run(resolve_model(client, "qwen3.5:2b"))
    assert model == "qwen3.5:2b"
    assert "no models installed" in note


def test_resolve_refuses_embedding_only_install():
    client = FakeOllama(["nomic-embed-text:latest"])
    model, note = asyncio.run(resolve_model(client, "qwen3.5:2b"))
    assert note == "no usable chat model installed"


def test_resolve_survives_unreachable_ollama():
    client = FakeOllama(error=OSError("connection refused"))
    model, note = asyncio.run(resolve_model(client, "qwen3.5:2b"))
    assert model == "qwen3.5:2b"
    assert "cannot reach ollama" in note
