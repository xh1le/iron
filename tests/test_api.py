from fastapi.testclient import TestClient

from backend.app import create_app


def test_health_and_settings():
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["ok"] is True
        assert health["name"] == "iron"
        token = client.get("/api/bootstrap").json()["token"]
        assert token
        headers = {"X-Iron-Token": token}
        settings = client.get("/api/settings").json()
        assert "workspace" in settings
        models = client.get("/api/models").json()
        assert "models" in models
        page = client.get("/")
        assert page.status_code == 200
        assert b"iron" in page.content.lower()
        projects = client.get("/api/projects").json()
        assert projects["projects"]
        pid = projects["projects"][0]["id"]
        chat = client.post("/api/chats", json={"project_id": pid, "title": "New chat"}, headers=headers).json()
        assert chat["id"].startswith("cht_")
        listed = client.get("/api/chats", params={"project_id": pid}).json()
        assert any(c["id"] == chat["id"] for c in listed["chats"])


def test_mutations_require_token():
    app = create_app()
    with TestClient(app) as client:
        projects = client.get("/api/projects").json()
        pid = projects["projects"][0]["id"]
        res = client.post("/api/chats", json={"project_id": pid, "title": "New chat"})
        assert res.status_code == 403


def test_mcp_server_endpoints():
    app = create_app()
    with TestClient(app) as client:
        token = client.get("/api/bootstrap").json()["token"]
        headers = {"X-Iron-Token": token}

        listed = client.get("/api/mcp/servers").json()
        assert "servers" in listed

        res = client.post("/api/mcp/servers", json={"name": "", "config": {"type": "stdio"}}, headers=headers).json()
        assert res["ok"] is False

        res = client.post(
            "/api/mcp/servers",
            json={"name": "demo", "config": {"type": "stdio", "command": "npx", "args": "a b"}},
            headers=headers,
        ).json()
        assert res["ok"] is True
        assert any(s["name"] == "demo" for s in res["servers"])

        listed = client.get("/api/mcp/servers").json()["servers"]
        demo = next(s for s in listed if s["name"] == "demo")
        assert demo["command"] == "npx"

        res = client.post("/api/mcp/servers", json={"name": "demo", "config": {"type": "stdio", "command": "x"}}, headers=headers).json()
        assert res["ok"] is False

        res = client.delete("/api/mcp/servers/demo", headers=headers).json()
        assert res["ok"] is True
        assert all(s["name"] != "demo" for s in res["servers"])

        res = client.delete("/api/mcp/servers/demo", headers=headers).json()
        assert res["ok"] is False
