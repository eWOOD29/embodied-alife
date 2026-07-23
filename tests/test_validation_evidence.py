from __future__ import annotations

from app.validation import build_soak_readiness


class DummyUpdater:
    def public_status(self) -> dict:
        return {"state": "current"}


def test_decision_text_does_not_count_as_weather_or_danger_evidence(engine) -> None:
    events = [
        {
            "id": 1,
            "sim_time": 1.0,
            "kind": "decision",
            "message": "Ari chose inspect before the weather worsens.",
            "data": {
                "decision": {
                    "action": "inspect",
                    "interrupt_if": ["danger_detected", "weather_worsens"],
                    "reason": "A wolf or storm might exist, but neither was observed.",
                }
            },
        }
    ]
    readiness = build_soak_readiness(
        engine=engine,
        updater=DummyUpdater(),
        events=events,
        model_responses=[],
        memories=[],
        snapshots=[],
        metrics={
            "events": {"decisions": 1, "final_action_success_rate": None},
            "model": {"llm_success_rate": None},
        },
        anomaly_checks={"status": "ok", "pending_memory_candidate": None},
    )

    coverage = readiness["scenario_coverage"]
    assert coverage["weather_transition"]["covered"] is False
    assert coverage["storm_exposure"]["covered"] is False
    assert coverage["wolf_or_danger_encounter"]["covered"] is False
    assert coverage["temperature_stress"]["covered"] is False
    assert readiness["protocol_version"] == 2
