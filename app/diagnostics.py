from __future__ import annotations

import os
import platform
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

from app.build_info import BUILD_COMMIT, BUILD_TIME_UTC, BUILD_VERSION
from app.serialization import finite_number, json_safe, json_safe_dict
from app.validation import build_soak_readiness

PROCESS_STARTED_AT = datetime.now(UTC)
DIAGNOSTIC_RECORD_LIMIT = 10000


def _text(value: Any, limit: int = 4000) -> str:
    if isinstance(value, str):
        text = value.replace("\x00", "").strip()
    elif isinstance(value, int) and not isinstance(value, bool):
        text = str(value)
    elif isinstance(value, float):
        number = finite_number(value)
        text = "" if number is None else str(number)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _number(value: Any, default: float | None = None, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    return finite_number(value, default, minimum=minimum, maximum=maximum)


def _mapping(value: Any) -> Mapping[Any, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any, limit: int = DIAGNOSTIC_RECORD_LIMIT) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for raw in value:
        if len(result) >= limit:
            break
        if isinstance(raw, Mapping):
            result.append(json_safe_dict(raw, max_depth=10, max_items=1000, max_text=4000, max_nodes=10000, max_source_items=20000))
    return result


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values[:DIAGNOSTIC_RECORD_LIMIT])
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 2)


def _package_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in ("fastapi", "uvicorn", "httpx", "pydantic", "python-dotenv", "packaging"):
        try:
            result[name] = metadata.version(name)
        except (metadata.PackageNotFoundError, ValueError):
            result[name] = None
    return result


def _redact_log_line(line: Any) -> str:
    text = _text(line, 4000)
    lowered = text.lower()
    if any(token in lowered for token in ("authorization:", "bearer ", "api_key=", "api-key=", "token=")):
        return "[REDACTED POSSIBLE CREDENTIAL LINE]"
    return text


def _recent_logs(data_dir: Path, max_lines: int = 250) -> dict[str, Any]:
    candidates = [data_dir / "runtime" / "update-worker.log", data_dir / "runtime" / "server.log", data_dir / "runtime" / "app.log"]
    logs: dict[str, Any] = {}
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
            logs[path.name] = {"path": "<local-path-omitted>", "line_count_included": len(lines), "lines": [_redact_log_line(line) for line in lines]}
        except OSError:
            logs[path.name] = {"path": "<local-path-omitted>", "error": "log_read_failed"}
    if "server.log" not in logs and "app.log" not in logs:
        logs["server_stdout"] = {"available": False, "note": "No persistent application server log file was available."}
    return logs


def _model_metrics(model_responses: list[dict[str, Any]]) -> dict[str, Any]:
    values = _records(model_responses)
    latencies: list[float] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    sources: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    errors = 0
    finish_reasons: Counter[str] = Counter()
    attempts: Counter[str] = Counter()
    for item in values:
        latency = _number(item.get("latency_ms"), None, minimum=0.0, maximum=1_000_000_000.0)
        if latency is not None:
            latencies.append(latency)
        prompt = _number(item.get("prompt_tokens"), None, minimum=0.0, maximum=1_000_000_000.0)
        completion = _number(item.get("completion_tokens"), None, minimum=0.0, maximum=1_000_000_000.0)
        if prompt is not None:
            prompt_tokens.append(int(prompt))
        if completion is not None:
            completion_tokens.append(int(completion))
        sources[_text(item.get("source"), 80) or "unknown"] += 1
        statuses[_text(item.get("status"), 80) or "unknown"] += 1
        if item.get("error"):
            errors += 1
        provider = _mapping(item.get("provider"))
        finish_reasons[_text(provider.get("finish_reason"), 80) or "unknown"] += 1
        attempts[_text(provider.get("request_attempts"), 80) or "unknown"] += 1
    total = len(values)
    return {
        "total": total,
        "source_counts": dict(sources),
        "status_counts": dict(statuses),
        "error_count": errors,
        "llm_success_rate": round(sources.get("llm", 0) / total, 4) if total else None,
        "finish_reason_counts": dict(finish_reasons),
        "request_attempt_counts": dict(attempts),
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
    values = _records(events)
    kind_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    decisions = plans = belief_updates = final_results = successes = failures = 0
    for event in values:
        kind = _text(event.get("kind"), 80) or "unknown"
        kind_counts[kind] += 1
        data = _mapping(event.get("data"))
        if kind == "decision":
            decisions += 1
            decision = _mapping(data.get("decision"))
            plans += int(bool(decision.get("plan")))
            belief_updates += int(bool(decision.get("belief_updates")))
        if kind != "action_result" or data.get("reason") == "started":
            continue
        final_results += 1
        success = data.get("success") is True
        successes += int(success)
        failures += int(not success)
        action_counts[_text(data.get("action"), 80) or "unknown"] += 1
        if not success:
            failure_reasons[_text(data.get("reason"), 120) or "unknown"] += 1
    return {
        "event_kind_counts": dict(kind_counts),
        "decisions": decisions,
        "decisions_with_plans": plans,
        "decisions_with_belief_updates": belief_updates,
        "final_action_results": final_results,
        "successful_final_actions": successes,
        "failed_final_actions": failures,
        "final_action_success_rate": round(successes / final_results, 4) if final_results else None,
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


def build_diagnostic_bundle(*, engine: Any, updater: Any, health: dict[str, Any], application_version: str) -> dict[str, Any]:
    exported_at = datetime.now(UTC)
    try:
        memory_records = engine.vault.list_records(limit=DIAGNOSTIC_RECORD_LIMIT, scan_limit=DIAGNOSTIC_RECORD_LIMIT)
    except Exception:
        memory_records = []
    memories = []
    for record in memory_records:
        try:
            raw = record.to_dict()
        except Exception:
            continue
        memories.append(json_safe_dict(raw, max_depth=8, max_items=512, max_text=4000, max_nodes=5000, max_source_items=10000))
    try:
        events = _records(engine.database.list_events(limit=DIAGNOSTIC_RECORD_LIMIT))
    except Exception:
        events = []
    try:
        model_responses = _records(engine.database.list_model_responses(limit=DIAGNOSTIC_RECORD_LIMIT))
    except Exception:
        model_responses = []
    try:
        snapshots = _records(engine.snapshots.list())[:1000]
    except Exception:
        snapshots = []
    process_uptime = max(0.0, (exported_at - PROCESS_STARTED_AT).total_seconds())
    event_metrics = _event_metrics(events)
    model_metrics = _model_metrics(model_responses)
    metrics = {"model": model_metrics, "events": event_metrics}
    duplicate_restore_events = sum(
        1
        for left, right in zip(events, events[1:])
        if left.get("kind") == right.get("kind") == "system"
        and left.get("message") == right.get("message") == "Restored the latest local runtime state."
        and left.get("sim_time") == right.get("sim_time")
    )
    try:
        live_instances = engine.live_instance_count(engine.database.path) if hasattr(engine, "live_instance_count") else None
    except Exception:
        live_instances = None
    anomaly_checks = {
        "live_simulation_engine_instances": _number(live_instances),
        "multiple_live_engines_detected": isinstance(live_instances, int) and not isinstance(live_instances, bool) and live_instances > 1,
        "duplicate_adjacent_restore_event_pairs": duplicate_restore_events,
        "pending_memory": json_safe(getattr(engine, "pending_memory", None), max_depth=6, max_items=128, max_text=2000, max_nodes=2000, max_source_items=4000),
        "status": "warning" if (isinstance(live_instances, int) and live_instances > 1) or duplicate_restore_events else "ok",
    }
    try:
        soak_readiness = build_soak_readiness(
            engine=engine,
            updater=updater,
            events=events,
            model_responses=model_responses,
            memories=memories,
            snapshots=snapshots,
            metrics=metrics,
            anomaly_checks=anomaly_checks,
        )
    except Exception:
        soak_readiness = {"status": "unavailable", "reason": "malformed_state_omitted"}

    try:
        observer_state = engine.observer_state(include_map=True)
    except Exception:
        observer_state = {"status": "unavailable", "reason": "malformed_state_omitted"}
    try:
        serialized_state = engine.serialize()
    except Exception:
        serialized_state = {"status": "unavailable", "reason": "malformed_state_omitted"}
    try:
        llm_configuration = engine.brain.public_configuration()
    except Exception:
        llm_configuration = {"status": "unavailable"}
    try:
        update_status = updater.public_status()
    except Exception:
        update_status = {"status": "unavailable"}

    bundle = {
        "diagnostic_bundle": {
            "schema_version": 3,
            "exported_at_utc": exported_at.isoformat(),
            "application": "embodied-alife",
            "application_version": _text(application_version, 80),
            "run_id": _text(getattr(engine, "run_id", None), 160),
            "world_generation_id": _text(getattr(engine, "world_generation_id", None), 160),
            "privacy": {
                "api_keys_included": False,
                "environment_file_included": False,
                "raw_prompts_included": False,
                "local_paths_included": False,
                "note": "Credentials, raw environment contents, prompts, arbitrary object representations, and local filesystem paths are excluded.",
            },
        },
        "health": json_safe_dict(health, max_depth=6, max_items=256, max_text=2000, max_nodes=4000, max_source_items=8000),
        "build_and_runtime": {
            "build_commit": _text(BUILD_COMMIT, 160),
            "build_time_utc": _text(BUILD_TIME_UTC, 160),
            "build_version": _text(BUILD_VERSION, 80),
            "python_version": _text(sys.version, 400),
            "python_executable": "<local-path-omitted>",
            "platform": _text(platform.platform(), 400),
            "machine": _text(platform.machine(), 160),
            "processor": _text(platform.processor(), 400),
            "operating_system": {"name": _text(os.name, 80), "system": _text(platform.system(), 80), "release": _text(platform.release(), 160)},
            "process_id": os.getpid(),
            "process_started_at_utc": PROCESS_STARTED_AT.isoformat(),
            "process_uptime_seconds": round(process_uptime, 2),
            "launch_argv": ["<argument-omitted>" for _ in sys.argv[:32]],
            "working_directory": "<local-path-omitted>",
            "database_path": "<local-path-omitted>",
            "memory_path": "<local-path-omitted>",
            "dependency_versions": _package_versions(),
        },
        "observer_state": observer_state,
        "serialized_engine_state": serialized_state,
        "llm_configuration": llm_configuration,
        "update_status": update_status,
        "durable_memories": memories,
        "snapshots": snapshots,
        "metrics": metrics,
        "anomaly_checks": anomaly_checks,
        "soak_readiness": soak_readiness,
        "recent_logs": _recent_logs(engine.settings.data_dir),
        "persisted_events": events,
        "model_responses": model_responses,
        "counts": {
            "durable_memories": len(memories),
            "snapshots": len(snapshots),
            "persisted_events": len(events),
            "model_responses": len(model_responses),
            "in_memory_events": len(getattr(engine, "events", ())) if isinstance(getattr(engine, "events", None), (list, tuple, set)) else 0,
            "recent_memory_writes": len(getattr(engine, "memory_writes", ())) if isinstance(getattr(engine, "memory_writes", None), (list, tuple, set)) else 0,
        },
    }
    return json_safe_dict(bundle, max_depth=14, max_items=10000, max_text=4000, max_nodes=300000, max_source_items=350000)
