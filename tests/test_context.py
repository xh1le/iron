import asyncio

from backend.context import (
    build_memory_block,
    compact_messages,
    ctx_budget,
    dedupe_tool_result,
    estimate_tokens,
)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("x" * 320) == 100
    assert estimate_tokens("hi") >= 1


def test_ctx_budget_clamps():
    assert ctx_budget(65536, 0.6) > 0
    assert ctx_budget(65536, 0.6) < 65536
    assert ctx_budget(4096, 0.9) >= 1024


def test_compact_drops_oldest_keeps_head_and_tail():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a1" * 2000, "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "t1" * 2000},
        {"role": "assistant", "content": "a2" * 2000, "tool_calls": [{"id": "c2", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c2", "content": "t2" * 2000},
        {"role": "assistant", "content": "tail"},
    ]
    removed = compact_messages(messages, ctx_budget(8192, 0.5))
    assert removed > 0
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[-1]["content"] == "tail"
    roles = [m["role"] for m in messages]
    assert "assistant" in roles and "tool" in roles


def test_compact_truncates_big_tool_results():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a", "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "x" * 5000},
        {"role": "assistant", "content": "done"},
    ]
    compact_messages(messages, 10_000_000)
    tool = next(m for m in messages if m["role"] == "tool")
    assert len(tool["content"]) <= 1300


def test_dedupe_tool_result():
    messages = [
        {"role": "assistant", "content": "a", "tool_calls": [{"id": "c1", "function": {"name": "ls", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "_tool": "list_dir", "content": "same"},
    ]
    assert dedupe_tool_result(messages, "list_dir", "same") != "same"
    assert dedupe_tool_result(messages, "list_dir", "different") == "different"


def test_build_memory_block_injects_facts(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    project = store.projects()[0]
    store.memory_put(project["id"], "api endpoint", "POST /api/runs starts a run")
    chat = store.create_chat(project["id"], "New chat")
    block = asyncio.run(build_memory_block(store, project["id"], chat["id"], "how do I start a run?", 4000))
    assert "api endpoint" in block
    assert "PROJECT MEMORY" in block


def test_build_memory_block_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.store.iron_home", lambda: tmp_path)
    from backend.store import Store

    store = Store()
    project = store.projects()[0]
    block = asyncio.run(build_memory_block(store, project["id"], "", "anything", 4000))
    assert block == ""
    assert asyncio.run(build_memory_block(None, "", "", "", 4000)) == ""
