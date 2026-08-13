from fastapi.testclient import TestClient

from backend.app import create_app


def test_health_and_settings():
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["ok"] is True
        assert health["name"] == "iron"
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
        chat = client.post("/api/chats", json={"project_id": pid, "title": "New chat"}).json()
        assert chat["id"].startswith("cht_")
        listed = client.get("/api/chats", params={"project_id": pid}).json()
        assert any(c["id"] == chat["id"] for c in listed["chats"])
