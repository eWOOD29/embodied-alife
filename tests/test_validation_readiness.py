from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.updater.manager import UpdateManager


def test_validation_readiness_endpoint_reports_clean_run_identity(settings, engine) -> None:
    app = create_app(
        settings,
        engine=engine,
        updater=UpdateManager(settings),
        start_background=False,
    )
    with TestClient(app) as client:
        response = client.get("/api/validation/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["protocol_version"] == 1
    assert payload["run_id"] == engine.run_id
    assert payload["world_generation_id"] == engine.world_generation_id
    assert payload["ready_for_full_audit"] is False
    assert payload["required_scenarios_total"] > 10
    assert payload["instructions"]
