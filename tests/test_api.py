from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.version import __version__


def test_api_routes_and_static_dashboard(engine) -> None:
    app = create_app(engine.settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        root = client.get("/")
        assert root.status_code == 200
        assert "Observer: complete world truth" in root.text
        assert "Download diagnostic logs" in root.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/diagnostics.js").status_code == 200
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


def test_diagnostic_bundle_is_complete_and_excludes_secrets(engine) -> None:
    synthetic_secret = "".join(("diagnostic", "-synthetic", "-value", "-must-not-leak"))
    engine.settings.llm_api_key = synthetic_secret
    app = create_app(engine.settings, engine=engine, start_background=False)

    with TestClient(app) as client:
        response = client.get("/api/diagnostics/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert f"v{__version__}" in disposition

    bundle = response.json()
    assert bundle["diagnostic_bundle"]["schema_version"] == 3
    assert bundle["diagnostic_bundle"]["application_version"] == __version__
    assert bundle["diagnostic_bundle"]["privacy"]["api_keys_included"] is False
    assert bundle["health"]["version"] == __version__
    assert len(bundle["observer_state"]["world"]["tiles"]) == engine.world.size
    assert bundle["serialized_engine_state"]["world"]["seed"] == engine.world.seed
    assert "status" in bundle["llm_configuration"]
    assert "update_status" in bundle
    assert "durable_memories" in bundle
    assert "snapshots" in bundle
    assert bundle["persisted_events"]
    assert "model_responses" in bundle
    assert "soak_readiness" in bundle
    assert bundle["counts"]["persisted_events"] == len(bundle["persisted_events"])
    assert synthetic_secret not in response.text


def test_websocket_initial_state(engine) -> None:
    app = create_app(engine.settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            payload = socket.receive_json()
            assert payload["world"]["seed"] == engine.world.seed
            assert "agent_perception" in payload
            assert "tiles" not in payload["world"]
