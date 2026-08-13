from backend.parse import extract_text_tool_calls


def test_json_object():
    calls = extract_text_tool_calls('{"name":"spawn_task","arguments":{"title":"a","goal":"b"}}')
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "spawn_task"


def test_tasks_array():
    raw = '{"tasks":[{"title":"one","goal":"do one"},{"title":"two","goal":"do two"}]}'
    calls = extract_text_tool_calls(raw)
    assert len(calls) == 2
    assert all(c["function"]["name"] == "spawn_task" for c in calls)
