from __future__ import annotations

from collections import Counter
from typing import Any


def _matching_events(
    events: list[dict[str, Any]],
    *,
    kinds: set[str] | None = None,
    tokens: tuple[str, ...] = (),
    require_kind_for_tokens: bool = False,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    normalized_kinds = {kind.lower() for kind in kinds or set()}
    for event in events:
        kind = str(event.get("kind") or "").lower()
        message = str(event.get("message") or "").lower()
        data = str(event.get("data") or "").lower()
        kind_matches = bool(normalized_kinds and kind in normalized_kinds)
        token_matches = bool(tokens and any(token in message or token in data for token in tokens))
        if require_kind_for_tokens:
            if kind_matches and token_matches:
                matches.append(event)
        elif kind_matches or token_matches:
            matches.append(event)
    return matches


def _scenario(covered: bool, evidence: list[dict[str, Any]], note: str) -> dict[str, Any]:
    return {
        "covered": covered,
        "evidence_count": len(evidence),
        "latest_evidence": evidence[-1] if evidence else None,
        "note": note,
    }


def build_soak_readiness(
    *,
    engine,
    updater,
    events: list[dict[str, Any]],
    model_responses: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    metrics: dict[str, Any],
    anomaly_checks: dict[str, Any],
) -> dict[str, Any]:
    world = engine.world
    agent = engine.agent
    event_kinds = Counter(str(event.get("kind") or "unknown") for event in events)

    sleep = _matching_events(events, kinds={"action_result"}, tokens=("action sleep began", "already asleep"), require_kind_for_tokens=True)
    wake = _matching_events(events, kinds={"action_result"}, tokens=("ari woke", "reason': 'woke", '"reason": "woke"'), require_kind_for_tokens=True)
    consolidation = _matching_events(events, kinds={"consolidation"})
    weather = _matching_events(events, kinds={"weather"})
    storm = _matching_events(events, kinds={"weather"}, tokens=("storm",), require_kind_for_tokens=True)
    temperature = _matching_events(
        events,
        kinds={"physiology", "damage", "temperature"},
        tokens=("hypother", "overheat", "temperature", "too cold", "too hot"),
        require_kind_for_tokens=True,
    )
    wolf = _matching_events(
        events,
        kinds={"npc", "danger", "encounter", "action_result"},
        tokens=("wolf", "danger_detected"),
        require_kind_for_tokens=True,
    )
    interruption = [
        event
        for event in events
        if event.get("kind") == "action_result" and event.get("data", {}).get("reason") == "interrupted"
    ]
    shelter_built = [
        event
        for event in events
        if event.get("kind") == "action_result"
        and event.get("data", {}).get("action") == "build"
        and event.get("data", {}).get("success")
        and event.get("data", {}).get("reason") == "built"
    ]
    shelter_damage = _matching_events(
        events,
        kinds={"shelter"},
        tokens=("durability", "destroyed", "damaged"),
        require_kind_for_tokens=True,
    )
    regeneration = _matching_events(
        events,
        kinds={"resource", "regeneration"},
        tokens=("regenerat", "regrew", "replenish"),
        require_kind_for_tokens=True,
    )
    death = _matching_events(events, kinds={"death"}, tokens=("ari died", "agent died"))
    restart = _matching_events(events, kinds={"system"}, tokens=("restored the latest local runtime state",), require_kind_for_tokens=True)
    snapshot_events = _matching_events(events, kinds={"snapshot"})
    verified_memory = _matching_events(events, kinds={"memory_write"})
    memory_rejected = _matching_events(events, kinds={"memory_rejected", "memory_candidate_rejected"})

    update_status = updater.public_status()
    update_success = bool(
        update_status.get("installed_version")
        or update_status.get("last_installed_version")
        or update_status.get("state") in {"current", "idle", "ready"}
    )

    scenarios = {
        "sleep_and_wake": _scenario(bool(sleep and wake), sleep + wake, "A complete sleep action and authoritative waking outcome are required."),
        "memory_consolidation": _scenario(bool(consolidation), consolidation, "At least one sleep-related consolidation pass is required."),
        "multiple_day_night_cycles": _scenario(world.day >= 3, [], f"Current world day is {world.day}; target is day 3 or later."),
        "weather_transition": _scenario(bool(weather), weather, "At least one authoritative weather event is required."),
        "storm_exposure": _scenario(bool(storm), storm, "At least one authoritative storm event should occur during the run."),
        "temperature_stress": _scenario(bool(temperature), temperature, "Evidence of an authoritative hot/cold body response is required."),
        "wolf_or_danger_encounter": _scenario(bool(wolf), wolf, "At least one authoritative wolf/danger event should be observed."),
        "action_interruption": _scenario(bool(interruption), interruption, "At least one action should be interrupted by a declared condition."),
        "shelter_construction": _scenario(bool(shelter_built or world.shelters), shelter_built, "Ari should construct at least one shelter."),
        "shelter_degradation": _scenario(bool(shelter_damage), shelter_damage, "A shelter should experience weather damage or destruction."),
        "resource_regeneration": _scenario(bool(regeneration), regeneration, "At least one depleted resource should regenerate."),
        "death_path": _scenario(bool(death or not agent.alive), death, "The death path is optional for a healthy soak run but required for full lifecycle coverage."),
        "snapshot_save_or_load": _scenario(bool(snapshots or snapshot_events), snapshot_events, "At least one snapshot operation should be recorded."),
        "restart_restore_continuity": _scenario(bool(restart), restart, "Restart the app once and verify state restoration."),
        "verified_memory_commit": _scenario(bool(verified_memory or memories), verified_memory, "At least one outcome-verified durable memory should be committed."),
        "memory_filter_or_rejection": _scenario(bool(memory_rejected), memory_rejected, "At least one non-durable or invalid memory candidate should be filtered safely."),
        "updater_continuity": _scenario(update_success, [], "Updater state should remain healthy after installation and restart."),
    }

    required = [name for name in scenarios if name != "death_path"]
    covered_required = [name for name in required if scenarios[name]["covered"]]
    decisions = int(metrics.get("events", {}).get("decisions") or 0)
    llm_success_rate = metrics.get("model", {}).get("llm_success_rate")
    action_success_rate = metrics.get("events", {}).get("final_action_success_rate")
    blocking_anomalies = anomaly_checks.get("status") != "ok"
    pending_memory = bool(anomaly_checks.get("pending_memory_candidate"))

    quality_gates = {
        "minimum_world_day_3": world.day >= 3,
        "minimum_100_decisions": decisions >= 100,
        "llm_success_rate_at_least_95_percent": llm_success_rate is not None and llm_success_rate >= 0.95,
        "final_action_success_rate_at_least_80_percent": action_success_rate is not None and action_success_rate >= 0.80,
        "no_structural_anomalies": not blocking_anomalies,
        "no_unresolved_pending_memory": not pending_memory,
        "agent_alive_at_export": bool(agent.alive),
    }

    ready_for_full_audit = all(quality_gates.values()) and len(covered_required) == len(required)
    return {
        "protocol_version": 2,
        "run_id": getattr(engine, "run_id", None),
        "world_generation_id": getattr(engine, "world_generation_id", None),
        "current_world_day": world.day,
        "current_sim_time": round(world.sim_time, 2),
        "event_kind_counts": dict(event_kinds),
        "scenario_coverage": scenarios,
        "required_scenarios_covered": len(covered_required),
        "required_scenarios_total": len(required),
        "missing_required_scenarios": [name for name in required if not scenarios[name]["covered"]],
        "quality_gates": quality_gates,
        "ready_for_full_audit": ready_for_full_audit,
        "instructions": [
            "Begin with Reset seed so the run has a clean experiment identity and empty world-specific memory/history.",
            "Run at 1x or 10x for at least three complete simulated days; avoid 100x for the primary behavioral audit.",
            "Leave the local LLM enabled and do not change models during the primary run.",
            "Save a snapshot after day 1, restart the application once, and confirm the run resumes before continuing.",
            "Download diagnostics at the end and attach the JSON bundle for audit.",
        ],
    }
