from __future__ import annotations

import os
import platform
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from app.build_info import BUILD_COMMIT, BUILD_TIME_UTC, BUILD_VERSION

PROCESS_STARTED_AT = datetime.now(UTC)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 2)


def _package_versions() -> dict[str, str | None]:
    names = ["fastapi", "uvicorn", "httpx", "pydantic", "python-dotenv", "packaging"]
    result: dict[str, str | None] = {}
    for name in names:
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def _redact_log_line(line: str) -> str:
    lowered = line.lower()
    if any(token in lowered for token in ("authorization:", "bearer ", "api_key=", "api-key=")):
        return "[REDACTED POSSIBLE CREDENTIAL LINE]"
    return line.rstrip("\r\n")[:4000]


def _recent_logs(data_dir: Path, max_lines: int = 250) -> dict[str, Any]:
    candidates = [
        data_dir / "runtime" / "update-worker.log",
        data_dir / "runtime" / "server.log",
        data_dir / "runtime" / "app.log",
    ]
    logs: dict[str, Any] = {}
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
            logs[path.name] = {
                "path": str(path),
                "line_count_included": len(lines),
                "lines": [_redact_log_line(line) for line in lines],
            }
        except OSError as exc:
            logs[path.name] = {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    if "server.log" not in logs and "app.log" not in logs:
        logs["server_stdout"] = {
            "available": False,
            "note": "The managed launcher currently writes server logs to its console; no persistent server log file was found.",
        }
    return logs


def _model_metrics(model_responses: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item["latency_ms"]) for item in model_responses if item.get("latency_ms") is not None]
    prompt_tokens = [int(item["prompt_tokens"]) for item in model_responses if item.get("prompt_tokens") is not None]
    completion_tokens = [int(item["completion_tokens"]) for item in model_responses if item.get("completion_tokens") is not None]
    sources = Counter(item.get("source") or "unknown" for item in model_responses)
    statuses = Counter(item.get("status") or "unknown" for item in model_responses)
    errors = [item for item in model_responses if item.get("error")]
    return {
        "total": len(model_responses),
        "source_counts": dict(sources),
        "status_counts": dict(statuses),
        "error_count": len(errors),
        "llm_success_rate": round(sources.get("llm", 0) / len(model_responses), 4) if model_responses else None,
        "latency_ms": {
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "p95": _percentile(latencies, 0.95),
            "maximum": round(max(latencies), 2) if latencies else None,
        },
        "tokens": {
            "prompt_total": sum(prompt_tokens),
            "completion_total": sum(completion_tokens),
            "prompt_median": round(statistics.median(prompt_tokens), 2) if prompt_tokens else None,
            "completion_median": round(statistics.median(completion_tokens), 2) if completion_tokens else None,
        },
    }


def _event_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    kind_counts = Counter(event.get("kind") or "unknown" for event in events)
    action_results = [event for event in events if event.get("kind") == "action_result"]
    final_results = [event for event in action_results if event.get("data", {}).get("reason") != "started"]
    successes = [event for event in final_results if event.get("data", {}).get("success")]
    failures = [event for event in final_results if not event.get("data", {}).get("success")]
    action_counts = Counter(event.get("data", {}).get("action") or "unknown" for event in final_results)
    failure_reasons = Counter(event.get("data", {}).get("reason") or "unknown" for event in failures)
    decision_events = [event for event in events if event.get("kind") == "decision"]
    plans = 0
    belief_updates = 0
    for event in decision_events:
        decision = event.get("data", {}).get("decision") or {}
        if decision.get("plan"):
            plans += 1
        if decision.get("belief_updates"):
            belief_updates += 1
    return {
        "event_kind_counts": dict(kind_counts),
        "decisions": len(decision_events),
        "decisions_with_plans": plans,
        "decisions_with_belief_updates": belief_updates,
        "final_action_results": len(final_results),
        "successful_final_actions": len(successes),
        "failed_final_actions": len(failures),
        "final_action_success_rate": round(len(successes) / len(final_results), 4) if final_results else None,
        "final_action_counts": dict(action_counts),
        "failure_reason_counts": dict(failure_reasons),
        "memory": {
            "candidates_staged": kind_counts.get("memory_candidate", 0),
            "candidates_filtered": kind_counts.get("memory_candidate_rejected", 0),
            "verified_writes": kind_counts.get("memory_write", 0),
            "outcome_or_validation_rejections": kind_counts.get("memory_rejected", 0),
            "consolidations": kind_counts.get("consolidation", 0),
        },
    }


def build_diagnostic_bundle(
    *,
    engine,
    updater,
    health: dict[str, Any],
    application_version: str,
) -> dict[str, Any]:
    exported_at = datetime.now(UTC)
    memories = [record.to_dict() for record in engine.vault.list_records()]
    events = engine.database.list_events(limit=10000)
    model_responses = engine.database.list_model_responses(limit=10000)
    snapshots = engine.snapshots.list()
    process_uptime = max(0.0, (exported_at - PROCESS_STARTED_AT).total_seconds())
    event_metrics = _event_metrics(events)
    model_metrics = _model_metrics(model_responses)
    duplicate_restore_events = sum(
        1
        for left, right in zip(events, events[1:])
        if left.get("kind") == right.get("kind") == "system"
        and left.get("message") == right.get("message") == "Restored the latest local runtime state."
        and left.get("sim_time") == right.get("sim_time")
    )
    live_instances = engine.live_instance_count() if hasattr(engine, "live_instance_count") else None

    return {
        "diagnostic_bundle": {
            "schema_version": 2,
            "exported_at_utc": exported_at.isoformat(),
            "application": "embodied-alife",
            "application_version": application_version,
            "run_id": getattr(engine, "run_id", None),
            "world_generation_id": getattr(engine, "world_generation_id", None),
            "privacy": {
                "api_keys_included": False,
                "environment_file_included": False,
                "raw_prompts_included": False,
                "note": "Public runtime configuration and sanitized log tails are included; credentials, raw .env contents, and raw prompts are excluded.",
            },
            "manifest": {
                "health": "Concise process, simulation, model, and updater health.",
                "build_and_runtime": "Build commit, package identity, Python/platform/process information, paths, uptime, and dependency versions.",
                "observer_state": "Complete observer-facing world state, including map truth.",
                "serialized_engine_state": "Persistable simulation state used for snapshots and restart recovery.",
                "llm_configuration": "Non-secret local LLM settings, cached model catalog, provider metadata, and current status.",
                "metrics": "Aggregate model, action, planning, belief, and memory reliability statistics.",
                "anomaly_checks": "Known structural integrity checks such as duplicate engines and duplicate restore events.",
                "recent_logs": "Sanitized tails of persistent runtime logs when available.",
                "persisted_events": "Up to 10,000 persisted timeline events in chronological order.",
                "model_responses": "Up to 10,000 persisted model/fallback responses with usage, latency, and errors.",
            },
        },
        "health": health,
        "build_and_runtime": {
            "build_commit": BUILD_COMMIT,
            "build_time_utc": BUILD_TIME_UTC,
            "build_version": BUILD_VERSION,
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "operating_system": {"name": os.name, "system": platform.system(), "release": platform.release()},
            "process_id": os.getpid(),
            "process_started_at_utc": PROCESS_STARTED_AT.isoformat(),
            "process_uptime_seconds": round(process_uptime, 2),
            "launch_argv": list(sys.argv),
            "working_directory": str(Path.cwd()),
            "database_path": str(engine.database.path),
            "memory_path": str(engine.vault.root),
            "dependency_versions": _package_versions(),
        },
        "observer_state": engine.observer_state(include_map=True),
        "serialized_engine_state": engine.serialize(),
        "llm_configuration": engine.brain.public_configuration(),
        "update_status": updater.public_status(),
        "durable_memories": memories,
        "snapshots": snapshots,
        "metrics": {"model": model_metrics, "events": event_metrics},
        "anomaly_checks": {
            "live_simulation_engine_instances": live_instances,
            "multiple_live_engines_detected": live_instances is not None and live_instances > 1,
            "duplicate_adjacent_restore_event_pairs": duplicate_restore_events,
            "pending_memory_candidate": engine.pending_memory,
            "status": "warning" if (live_instances is not None and live_instances > 1) or duplicate_restore_events else "ok",
        },
        "recent_logs": _recent_logs(engine.settings.data_dir),
        "persisted_events": events,
        "model_responses": model_responses,
        "counts": {
            "durable_memories": len(memories),
            "snapshots": len(snapshots),
            "persisted_events": len(events),
            "model_responses": len(model_responses),
            "in_memory_events": len(engine.events),
            "recent_memory_writes": len(engine.memory_writes),
        },
    }
