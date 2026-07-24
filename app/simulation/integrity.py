from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
from pathlib import Path
from typing import Any, Mapping

PROOF_VERSION = 1
KEY_FILE_NAME = "ari-provenance.key"
MEMORY_LEDGER_NAME = "ari-memory-proofs.json"
PROOF_TEXT_LIMIT = 256
MAX_LEDGER_ENTRIES = 4096

CONTROLLED_CREATION_PATHS = {
    "deterministic_starter",
    "validated_model_response",
    "validated_perception",
    "validated_action_event",
    "validated_consolidation",
    "explicit_migration",
}

_ALLOWED_SOURCES = {
    "deterministic_starter": {"system_initialization"},
    "validated_model_response": {"agent", "ari", "inference", "model_belief_update"},
    "validated_perception": {"perception", "observation"},
    "validated_action_event": {"action", "event", "perception"},
    "validated_consolidation": {"consolidation", "reflection", "memory"},
    "explicit_migration": {"legacy_migration", "system_initialization"},
}

_RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "key_item": ("key_item_id", "display_name", "description"),
    "task": (
        "task_id", "title", "description", "created_by", "status", "priority",
        "created_at", "updated_at", "parent_task_id", "linked_marker_ids", "linked_note_ids",
    ),
    "note": (
        "note_id", "title", "content", "tags", "status", "created_at", "updated_at",
        "linked_task_ids", "linked_marker_ids",
    ),
    "marker": (
        "marker_id", "label", "marker_type", "believed_location", "confidence", "status",
        "created_at", "updated_at", "linked_task_ids", "linked_note_ids",
    ),
    "belief": (
        "belief_id", "claim", "confidence", "basis", "status", "first_formed_at",
        "last_tested_at", "supporting_evidence_ids", "contradicting_evidence_ids", "source_type",
    ),
    "episode": (
        "episode_id", "source_event_id", "simulation_timestamp", "summary", "category", "salience",
        "status", "linked_task_ids", "linked_note_ids", "linked_belief_ids", "linked_marker_ids",
        "linked_memory_ids",
    ),
}


def _member(value: Any, name: str, default: Any = None) -> Any:
    try:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)
    except Exception:
        return default


def _text(value: Any, limit: int = PROOF_TEXT_LIMIT) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)[:limit]
    if isinstance(value, float):
        return (str(value) if math.isfinite(value) else "")[:limit]
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value[:limit]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(-10**15, min(10**15, value))
    if isinstance(value, float):
        return max(-10**15, min(10**15, value)) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number):
            return None
        return max(-10**15, min(10**15, number))
    return None


def _canonical(value: Any, *, depth: int = 0, max_items: int = 64) -> Any:
    if depth > 6:
        return None
    if value is None or isinstance(value, bool):
        return value
    number = _number(value)
    if number is not None and not isinstance(value, str):
        return number
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        scanned = 0
        for raw_key, raw_value in value.items():
            scanned += 1
            if scanned > max_items:
                result["__truncated__"] = True
                break
            key = _text(raw_key, 160)
            if not key:
                continue
            projected = _canonical(raw_value, depth=depth + 1, max_items=max_items)
            if projected is not None:
                result[key] = projected
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for index, item in enumerate(value):
            if index >= max_items:
                result.append("<truncated>")
                break
            projected = _canonical(item, depth=depth + 1, max_items=max_items)
            if projected is not None:
                result.append(projected)
        return result
    if isinstance(value, (set, frozenset)):
        if len(value) > max_items:
            return ["<unordered-omitted>"]
        projected = [_canonical(item, depth=depth + 1, max_items=max_items) for item in value]
        projected = [item for item in projected if item is not None]
        return sorted(projected, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return None


def _provenance(record: Any) -> Any:
    return _member(record, "provenance")


def _provenance_value(record: Any, name: str, default: Any = None) -> Any:
    return _member(_provenance(record), name, default)


def _record_identity(family: str, record: Any) -> str:
    id_field = {
        "key_item": "key_item_id",
        "task": "task_id",
        "note": "note_id",
        "marker": "marker_id",
        "belief": "belief_id",
        "episode": "episode_id",
    }.get(family, "id")
    return _text(_member(record, id_field), 160)


def record_payload(family: str, record: Any, *, creation_path: str | None = None, source_ref: str | None = None) -> dict[str, Any] | None:
    fields = _RECORD_FIELDS.get(family)
    identity = _record_identity(family, record)
    if not fields or not identity:
        return None
    path = _text(creation_path if creation_path is not None else _provenance_value(record, "creation_path"), 80)
    reference = _text(source_ref if source_ref is not None else _provenance_value(record, "source_id"), 200)
    source_type = _text(_provenance_value(record, "source_type"), 80).lower()
    content = {name: _canonical(_member(record, name)) for name in fields}
    return {
        "proof_version": PROOF_VERSION,
        "family": family,
        "identity": identity,
        "creation_path": path,
        "source_type": source_type,
        "source_ref": reference,
        "content": content,
    }


def _encoded(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(key: bytes, payload: Mapping[str, Any]) -> str:
    return hmac.new(key, _encoded(payload), hashlib.sha256).hexdigest()


def _set_provenance_value(record: Any, name: str, value: Any) -> bool:
    provenance = _provenance(record)
    if provenance is None:
        return False
    try:
        if isinstance(provenance, dict):
            provenance[name] = value
        else:
            setattr(provenance, name, value)
        return True
    except Exception:
        return False


def attach_key(agent: Any, key: bytes | None) -> None:
    try:
        agent._ari_integrity_key = key
    except Exception:
        return


def agent_key(agent: Any) -> bytes | None:
    key = _member(agent, "_ari_integrity_key")
    return key if isinstance(key, bytes) and len(key) >= 32 else None


def seal_record(
    family: str,
    record: Any,
    key: bytes | None,
    creation_path: str,
    *,
    source_type: str | None = None,
    source_ref: str | None = None,
) -> bool:
    if not key or creation_path not in CONTROLLED_CREATION_PATHS:
        return False
    if source_type is not None and not _set_provenance_value(record, "source_type", _text(source_type, 80).lower()):
        return False
    if source_ref is not None and not _set_provenance_value(record, "source_id", _text(source_ref, 200)):
        return False
    if not _set_provenance_value(record, "creation_path", creation_path):
        return False
    if not _set_provenance_value(record, "proof_version", PROOF_VERSION):
        return False
    payload = record_payload(family, record, creation_path=creation_path, source_ref=source_ref)
    if payload is None:
        return False
    proof = _digest(key, payload)
    return _set_provenance_value(record, "proof", proof)


def verify_record(family: str, record: Any, agent: Any) -> bool:
    key = agent_key(agent)
    if key is None:
        return False
    creation_path = _text(_provenance_value(record, "creation_path"), 80)
    source_type = _text(_provenance_value(record, "source_type"), 80).lower()
    proof = _text(_provenance_value(record, "proof"), 128)
    version = _number(_provenance_value(record, "proof_version"))
    if creation_path not in CONTROLLED_CREATION_PATHS or version != PROOF_VERSION or len(proof) != 64:
        return False
    if source_type not in _ALLOWED_SOURCES.get(creation_path, set()):
        return False
    if family == "belief":
        visible_source = _text(_member(record, "source_type"), 80).lower()
        if visible_source and visible_source != source_type:
            return False
    payload = record_payload(family, record)
    return payload is not None and hmac.compare_digest(proof, _digest(key, payload))


def sign_payload(agent: Any, family: str, value: Any, creation_path: str, *, source_ref: str) -> dict[str, Any] | None:
    key = agent_key(agent)
    if key is None or creation_path not in CONTROLLED_CREATION_PATHS:
        return None
    payload = {
        "proof_version": PROOF_VERSION,
        "family": family,
        "creation_path": creation_path,
        "source_ref": _text(source_ref, 200),
        "content": _canonical(value, max_items=256),
    }
    return {
        "proof_version": PROOF_VERSION,
        "creation_path": creation_path,
        "source_ref": payload["source_ref"],
        "proof": _digest(key, payload),
    }


def verify_payload(agent: Any, family: str, value: Any, evidence: Any) -> bool:
    key = agent_key(agent)
    if key is None or not isinstance(evidence, Mapping):
        return False
    creation_path = _text(evidence.get("creation_path"), 80)
    source_ref = _text(evidence.get("source_ref"), 200)
    proof = _text(evidence.get("proof"), 128)
    if creation_path not in CONTROLLED_CREATION_PATHS or _number(evidence.get("proof_version")) != PROOF_VERSION or len(proof) != 64:
        return False
    payload = {
        "proof_version": PROOF_VERSION,
        "family": family,
        "creation_path": creation_path,
        "source_ref": source_ref,
        "content": _canonical(value, max_items=256),
    }
    return hmac.compare_digest(proof, _digest(key, payload))


def _knowledge_key(family: str, identity: str) -> str:
    return f"{_text(family, 48)}:{_text(identity, 160)}"


def seal_knowledge(agent: Any, family: str, identity: str, value: Any, creation_path: str, *, source_ref: str = "") -> bool:
    key = agent_key(agent)
    proofs = _member(agent, "ari_knowledge_proofs")
    if key is None or not isinstance(proofs, dict) or creation_path not in CONTROLLED_CREATION_PATHS:
        return False
    evidence = sign_payload(agent, f"knowledge:{family}:{_text(identity, 160)}", value, creation_path, source_ref=source_ref)
    if evidence is None:
        return False
    proofs[_knowledge_key(family, identity)] = evidence
    return True


def verify_knowledge(agent: Any, family: str, identity: str, value: Any) -> bool:
    proofs = _member(agent, "ari_knowledge_proofs")
    if not isinstance(proofs, Mapping):
        return False
    evidence = proofs.get(_knowledge_key(family, identity))
    return verify_payload(agent, f"knowledge:{family}:{_text(identity, 160)}", value, evidence)


def state_contains_proofs(value: Any, *, budget: int = 5000) -> bool:
    seen: set[int] = set()

    def visit(current: Any, remaining: list[int]) -> bool:
        if remaining[0] <= 0:
            return False
        remaining[0] -= 1
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                return False
            seen.add(identity)
            try:
                proof = current.get("proof")
                if isinstance(proof, str) and len(proof) == 64:
                    return True
                for index, item in enumerate(current.values()):
                    if index >= 512:
                        break
                    if visit(item, remaining):
                        return True
            finally:
                seen.discard(identity)
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in seen:
                return False
            seen.add(identity)
            try:
                for index, item in enumerate(current):
                    if index >= 512:
                        break
                    if visit(item, remaining):
                        return True
            finally:
                seen.discard(identity)
        return False

    return visit(value, [budget])


def load_or_create_key(runtime_dir: Path, *, allow_create: bool) -> bytes | None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / KEY_FILE_NAME
    if path.is_file():
        try:
            raw = bytes.fromhex(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None
        return raw if len(raw) >= 32 else None
    if not allow_create:
        return None
    key = secrets.token_bytes(32)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(key.hex() + "\n", encoding="ascii")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    return key


def _memory_payload(record: Any, creation_path: str, source_ref: str) -> dict[str, Any]:
    return {
        "proof_version": PROOF_VERSION,
        "family": "durable_memory",
        "identity": _text(_member(record, "id"), 160),
        "creation_path": creation_path,
        "source_ref": _text(source_ref, 200),
        "content": {
            name: _canonical(_member(record, name))
            for name in ("id", "category", "title", "content", "importance", "tags", "created_at", "sim_time", "path")
        },
    }


def _load_memory_ledger(runtime_dir: Path) -> dict[str, Any]:
    path = runtime_dir / MEMORY_LEDGER_NAME
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= MAX_LEDGER_ENTRIES:
            break
        if isinstance(key, str) and isinstance(item, dict):
            result[key[:160]] = item
    return result


def _write_memory_ledger(runtime_dir: Path, ledger: Mapping[str, Any]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / MEMORY_LEDGER_NAME
    temporary = path.with_suffix(".tmp")
    bounded = dict(list(ledger.items())[-MAX_LEDGER_ENTRIES:])
    temporary.write_text(json.dumps(bounded, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def seal_memory_record(runtime_dir: Path, record: Any, key: bytes | None, creation_path: str, *, source_ref: str) -> bool:
    if key is None or creation_path not in {"validated_action_event", "validated_consolidation"}:
        return False
    identity = _text(_member(record, "id"), 160)
    if not identity:
        return False
    payload = _memory_payload(record, creation_path, source_ref)
    ledger = _load_memory_ledger(runtime_dir)
    ledger[identity] = {
        "proof_version": PROOF_VERSION,
        "creation_path": creation_path,
        "source_ref": _text(source_ref, 200),
        "proof": _digest(key, payload),
    }
    _write_memory_ledger(runtime_dir, ledger)
    return True


def verify_memory_record(runtime_dir: Path, record: Any, key: bytes | None) -> bool:
    if key is None:
        return False
    identity = _text(_member(record, "id"), 160)
    evidence = _load_memory_ledger(runtime_dir).get(identity)
    if not isinstance(evidence, Mapping):
        return False
    creation_path = _text(evidence.get("creation_path"), 80)
    source_ref = _text(evidence.get("source_ref"), 200)
    proof = _text(evidence.get("proof"), 128)
    if creation_path not in {"validated_action_event", "validated_consolidation"} or _number(evidence.get("proof_version")) != PROOF_VERSION or len(proof) != 64:
        return False
    return hmac.compare_digest(proof, _digest(key, _memory_payload(record, creation_path, source_ref)))



def safe_message(value: Any, limit: int = 4000) -> str:
    return _text(value, limit)


def _same_record(family: str, left: Any, right: Any) -> bool:
    left_payload = record_payload(family, left, creation_path="deterministic_starter", source_ref="starter")
    right_payload = record_payload(family, right, creation_path="deterministic_starter", source_ref="starter")
    if left_payload is None or right_payload is None:
        return False
    left_payload["source_type"] = "system_initialization"
    right_payload["source_type"] = "system_initialization"
    return left_payload["identity"] == right_payload["identity"] and left_payload["content"] == right_payload["content"]


def seal_deterministic_starters(agent: Any, key: bytes | None) -> None:
    if key is None:
        return
    from app.simulation.cognition import starter_key_items, starter_tasks

    expected_items = starter_key_items()
    actual_items = _member(agent, "key_items")
    if isinstance(actual_items, Mapping):
        for identity, expected in expected_items.items():
            actual = actual_items.get(identity)
            if actual is not None and _same_record("key_item", actual, expected):
                seal_record("key_item", actual, key, "deterministic_starter", source_type="system_initialization", source_ref="v0.4.0-starter-kit")

    expected_tasks = starter_tasks()
    actual_tasks = _member(agent, "tasks")
    if isinstance(actual_tasks, Mapping):
        for identity, expected in expected_tasks.items():
            actual = actual_tasks.get(identity)
            if actual is not None and _same_record("task", actual, expected):
                seal_record("task", actual, key, "deterministic_starter", source_type="system_initialization", source_ref="v0.4.0-starter-journal")
