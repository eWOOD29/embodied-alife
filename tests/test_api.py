from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_api_routes_and_static_dashboard(engine) -> None:
    app = create_app(engine.settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        root = client.get("/")
        assert root.status_code == 200
        assert "Observer: complete world truth" in root.text
        assert client.get("/static/app.js").status_code == 200
        state = client.get("/api/state")
        assert state.status_code == 200
        assert "tiles" not in state.json()["world"]
        world = client.get("/api/world")
        assert len(world.json()["world"]["tiles"]) == engine.world.size
        paused = client.post("/api/control", json={"action": "pause"})
        assert paused.json()["paused"] is True
        speed = client.post("/api/control", json={"action": "speed", "speed": 10})
        assert speed.json()["speed"] == 10
        bad = client.post("/api/control", json={"action": "speed", "speed": 3})
        assert bad.status_code == 400


def test_websocket_initial_state(engine) -> None:
    app = create_app(engine.settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            payload = socket.receive_json()
            assert payload["world"]["seed"] == engine.world.seed
            assert "agent_perception" in payload
            assert "tiles" not in payload["world"]
