from __future__ import annotations

from app.diagnostics import build_diagnostic_bundle
from app.llm.observed_client import ObservedBrainResult
from app.llm.schemas import ActionDecision
from app.storage.database import Database
from app.version import __version__


class DummyUpdater:
    def public_status(self) -> dict:
        return {"state": "idle", "current_version": __version__}


def _decision() -> ActionDecision:
    return ActionDecision(
        intent="Wait safely while validating diagnostics.",
        action="wait",
        target_id=None,
        direction=None,
        duration_seconds=0.2,
        interrupt_if=[],
        reason="Exercise provider metadata persistence.",
        plan=["Wait", "Reassess"],
        belief_updates={"diagnostics": "Provider metadata should be persisted."},
        memory_write=None,
    )


def test_model_response_provider_metadata_round_trip(settings) -> None:
    database = Database(settings.database_path)
    try:
        result = ObservedBrainResult(
            _decision(),
            "llm",
            "ok",
            latency_ms=12.5,
            prompt_tokens=100,
            completion_tokens=20,
            finish_reason="stop",
            provider_response_id="chatcmpl-test",
            request_attempts=2,
        )
        database.add_model_response(1.5, result)
        saved = database.list_model_responses()
        assert saved[0]["provider"] == {
            "finish_reason": "stop",
            "provider_response_id": "chatcmpl-test",
            "request_attempts": 2,
        }
    finally:
        database.close()


def test_diagnostic_bundle_v3_contains_runtime_metrics_soak_readiness_and_no_secrets(engine) -> None:
    engine.database.add_model_response(
        engine.world.sim_time,
        ObservedBrainResult(
            _decision(),
            "llm",
            "ok",
            latency_ms=10.0,
            prompt_tokens=50,
            completion_tokens=10,
            finish_reason="stop",
            provider_response_id="chatcmpl-test",
            request_attempts=1,
        ),
    )
    engine._record(
        "decision",
        "Ari chose wait: test",
        0.5,
        {"decision": _decision().model_dump(), "provider": {"finish_reason": "stop"}},
    )
    engine._record(
        "action_result",
        "wait: completed",
        0.5,
        {"success": True, "action": "wait", "reason": "completed", "details": "Action wait completed."},
    )

    bundle = build_diagnostic_bundle(
        engine=engine,
        updater=DummyUpdater(),
        health={"status": "ok", "version": __version__},
        application_version=__version__,
    )

    header = bundle["diagnostic_bundle"]
    assert header["schema_version"] == 3
    assert header["run_id"] == engine.run_id
    assert header["world_generation_id"] == engine.world_generation_id
    assert header["privacy"]["api_keys_included"] is False
    assert header["privacy"]["raw_prompts_included"] is False

    runtime = bundle["build_and_runtime"]
    assert runtime["python_version"]
    assert runtime["process_id"] > 0
    assert runtime["database_path"] == str(engine.database.path)
    assert "fastapi" in runtime["dependency_versions"]

    metrics = bundle["metrics"]
    assert metrics["model"]["total"] == 1
    assert metrics["model"]["finish_reason_counts"]["stop"] == 1
    assert metrics["events"]["decisions"] == 1
    assert metrics["events"]["final_action_success_rate"] == 1.0
    assert bundle["anomaly_checks"]["multiple_live_engines_detected"] is False
    assert bundle["model_responses"][0]["provider"]["finish_reason"] == "stop"

    readiness = bundle["soak_readiness"]
    assert readiness["protocol_version"] == 1
    assert readiness["run_id"] == engine.run_id
    assert readiness["ready_for_full_audit"] is False
    assert "multiple_day_night_cycles" in readiness["missing_required_scenarios"]
    assert readiness["instructions"]

    serialized = str(bundle).lower()
    assert "authorization: bearer" not in serialized
    assert "raw_prompts_included': true" not in serialized
