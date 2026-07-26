from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
from pathlib import Path
from typing import Any

PROOF_VERSION = 2
AUTHORIZATION_DOMAIN = "embodied-alife/ari-authorization"
KEY_FILE_NAME = "ari-provenance.key"
EPOCH_FILE_NAME = "ari-authorization-epoch.json"
MEMORY_LEDGER_NAME = "ari-memory-proofs.json"
MAX_LEDGER_ENTRIES = 4096
MAX_LINK_IDS = 512
MAX_GENERIC_ITEMS = 2048
MAX_GENERIC_NODES = 20000
MAX_GENERIC_DEPTH = 12

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

# A key may be used by several test agents. Production calls pass the agent as
# authority, so this registry is only a backwards-compatible default for older
# call sites and tests that seal with a raw key after attach_key().
_KEY_CONTEXTS: dict[bytes, tuple[str, str, str]] = {}


class AuthorizationError(ValueError):
    pass


def _exact_dict(value: Any) -> dict[str, Any] | None:
    return value if type(value) is dict else None


def _field(record: Any, name: str) -> Any:
    if type(record) is dict:
        return record.get(name)
    # Only project the exact built-in cognitive record classes. This avoids
    # invoking arbitrary properties or __getattr__ implementations.
    from app.simulation.belief_store import BeliefValue
    from app.simulation.cognition import BeliefRecord, EpisodeRecord, KeyItem, MapMarker, NoteRecord, TaskRecord

    if type(record) is BeliefValue:
        return record.get(name)
    if type(record) in {KeyItem, TaskRecord, NoteRecord, MapMarker, BeliefRecord, EpisodeRecord}:
        return getattr(record, name, None)
    raise AuthorizationError("unsupported_record_type")


def _provenance(record: Any) -> Any:
    return _field(record, "provenance")


def _provenance_field(record: Any, name: str) -> Any:
    provenance = _provenance(record)
    from app.simulation.cognition import Provenance

    if type(provenance) is dict:
        return provenance.get(name)
    if type(provenance) is Provenance:
        return getattr(provenance, name, None)
    raise AuthorizationError("unsupported_provenance_type")


def _set_provenance_value(record: Any, name: str, value: Any) -> bool:
    try:
        provenance = _provenance(record)
        from app.simulation.cognition import Provenance

        if type(record).__name__ == "BeliefValue" and type(record) is not dict:
            raw = record.get("provenance")
            if type(raw) is not dict:
                return False
            raw[name] = value
        elif type(provenance) is dict:
            provenance[name] = value
        elif type(provenance) is Provenance:
            setattr(provenance, name, value)
        else:
            return False
        return True
    except Exception:
        return False


def _strict_text(value: Any, maximum: int, *, allow_empty: bool = True) -> str:
    if type(value) is not str:
        raise AuthorizationError("text_type")
    if len(value) > maximum:
        raise AuthorizationError("text_too_long")
    if not allow_empty and not value:
        raise AuthorizationError("text_empty")
    return value


def _optional_text(value: Any, maximum: int) -> str | None:
    if value is None:
        return None
    return _strict_text(value, maximum)


def _finite(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or type(value) not in {int, float}:
        raise AuthorizationError("number_type")
    number = float(value)
    if not math.isfinite(number):
        raise AuthorizationError("number_nonfinite")
    if minimum is not None and number < minimum:
        raise AuthorizationError("number_below_minimum")
    if maximum is not None and number > maximum:
        raise AuthorizationError("number_above_maximum")
    return number


def _integer(value: Any, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise AuthorizationError("integer_type")
    if minimum is not None and value < minimum:
        raise AuthorizationError("integer_below_minimum")
    if maximum is not None and value > maximum:
        raise AuthorizationError("integer_above_maximum")
    return value


def _malformed_numeric_token(value: Any, default: float | int) -> dict[str, Any]:
    """Bind the complete supported malformed built-in value without authorizing ambiguity.

    Older persisted schemas can contain malformed built-in scalar/container values that
    Ari-facing projections normalize to a fixed safe default. The envelope authenticates
    the exact input type and complete supported value, so changing one malformed value to
    another still invalidates the proof. Arbitrary/custom objects remain unsupported.
    """
    if value is None:
        raw: Any = None
        input_type = "null"
    elif type(value) is bool:
        raw = value
        input_type = "bool"
    elif type(value) is str:
        raw = _strict_text(value, 12000)
        input_type = "string"
    elif type(value) in {list, dict}:
        raw = _strict_generic(value)
        input_type = "list" if type(value) is list else "map"
    elif type(value) is tuple:
        if len(value) > MAX_GENERIC_ITEMS:
            raise AuthorizationError("numeric_tuple_items")
        raw = [_strict_generic(item) for item in value]
        input_type = "tuple"
    elif type(value) is set:
        # Sets are unordered and therefore cannot receive record authority.
        raise AuthorizationError("numeric_set_type")
    elif type(value) is bytes:
        if len(value) > 12000:
            raise AuthorizationError("numeric_bytes_length")
        raw = value.hex()
        input_type = "bytes"
    elif type(value) is float and not math.isfinite(value):
        raw = "nan" if math.isnan(value) else ("positive_infinity" if value > 0 else "negative_infinity")
        input_type = "nonfinite_float"
    else:
        raise AuthorizationError("hostile_number_type")
    return {"input_type": input_type, "raw": raw, "normalized": default}


def _normalized_finite(
    value: Any,
    default: float = 0.0,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Any:
    if type(value) in {int, float} and not isinstance(value, bool):
        try:
            number = _finite(value, minimum=minimum, maximum=maximum)
        except AuthorizationError:
            if type(value) is float and not math.isfinite(value):
                return _malformed_numeric_token(value, default)
            raise
        return {"input_type": "int" if type(value) is int else "float", "value": number}
    return _malformed_numeric_token(value, default)


def _normalized_integer(value: Any, default: int = 0, *, minimum: int = -1_000_000_000, maximum: int = 1_000_000_000) -> Any:
    if type(value) is int and not isinstance(value, bool):
        parsed = _integer(value, minimum=minimum, maximum=maximum)
        return {"input_type": "int", "value": parsed}
    return _malformed_numeric_token(value, default)


def _string_list(value: Any, *, maximum: int = MAX_LINK_IDS, text_maximum: int = 160) -> list[str]:
    if type(value) is not list:
        raise AuthorizationError("list_type")
    if len(value) > maximum:
        raise AuthorizationError("list_too_long")
    result: list[str] = []
    for item in value:
        result.append(_strict_text(item, text_maximum, allow_empty=False))
    return result


def _origin(record: Any) -> str:
    return _strict_text(_provenance_field(record, "source_type"), 80, allow_empty=False).lower()


def _location_projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    location = _exact_dict(value)
    if location is None:
        raise AuthorizationError("location_type")
    result: dict[str, Any] = {}
    text_fields = {
        "direction": 120,
        "relative_direction": 120,
        "distance_band": 120,
        "relative_distance": 120,
        "description": 1000,
    }
    number_fields = {"x", "y", "distance", "uncertainty", "confidence", "certainty", "last_seen"}
    for name, limit in text_fields.items():
        if name in location:
            result[name] = _strict_text(location[name], limit)
    for name in number_fields:
        if name in location:
            result[name] = _normalized_finite(location[name], 0.0)
    return result


def _record_projection(family: str, record: Any) -> dict[str, Any]:
    origin = _origin(record)
    if family == "key_item":
        return {
            "key_item_id": _strict_text(_field(record, "key_item_id"), 16000, allow_empty=False),
            "display_name": _strict_text(_field(record, "display_name"), 12000),
            "description": _strict_text(_field(record, "description"), 12000),
            "origin": origin,
        }
    if family == "task":
        return {
            "task_id": _strict_text(_field(record, "task_id"), 16000, allow_empty=False),
            "title": _strict_text(_field(record, "title"), 12000),
            "description": _strict_text(_field(record, "description"), 12000),
            "created_by": _strict_text(_field(record, "created_by"), 1000),
            "status": _strict_text(_field(record, "status"), 32),
            "priority": _normalized_integer(_field(record, "priority")),
            "created_at": _normalized_finite(_field(record, "created_at"), 0.0),
            "updated_at": _normalized_finite(_field(record, "updated_at"), 0.0),
            "parent_task_id": _optional_text(_field(record, "parent_task_id"), 16000),
            "linked_marker_ids": _string_list(_field(record, "linked_marker_ids")),
            "linked_note_ids": _string_list(_field(record, "linked_note_ids")),
            "origin": origin,
        }
    if family == "note":
        return {
            "note_id": _strict_text(_field(record, "note_id"), 16000, allow_empty=False),
            "title": _strict_text(_field(record, "title"), 12000),
            "content": _strict_text(_field(record, "content"), 12000),
            "tags": _string_list(_field(record, "tags"), maximum=512, text_maximum=12000),
            "status": _strict_text(_field(record, "status"), 32),
            "created_at": _normalized_finite(_field(record, "created_at"), 0.0),
            "updated_at": _normalized_finite(_field(record, "updated_at"), 0.0),
            "linked_task_ids": _string_list(_field(record, "linked_task_ids")),
            "linked_marker_ids": _string_list(_field(record, "linked_marker_ids")),
            "origin": origin,
        }
    if family == "marker":
        return {
            "marker_id": _strict_text(_field(record, "marker_id"), 16000, allow_empty=False),
            "label": _strict_text(_field(record, "label"), 12000),
            "marker_type": _strict_text(_field(record, "marker_type"), 1000),
            "believed_location": _location_projection(_field(record, "believed_location")),
            "confidence": _normalized_finite(_field(record, "confidence"), 0.0, minimum=0.0, maximum=1.0),
            "status": _strict_text(_field(record, "status"), 32),
            "created_at": _normalized_finite(_field(record, "created_at"), 0.0),
            "updated_at": _normalized_finite(_field(record, "updated_at"), 0.0),
            "linked_task_ids": _string_list(_field(record, "linked_task_ids")),
            "linked_note_ids": _string_list(_field(record, "linked_note_ids")),
            "origin": origin,
        }
    if family == "belief":
        return {
            "belief_id": _strict_text(_field(record, "belief_id"), 16000, allow_empty=False),
            "claim": _strict_text(_field(record, "claim"), 12000),
            "confidence": _normalized_finite(_field(record, "confidence"), 0.5, minimum=0.0, maximum=1.0),
            "basis": _strict_text(_field(record, "basis"), 12000),
            "status": _strict_text(_field(record, "status"), 32),
            "first_formed_at": _normalized_finite(_field(record, "first_formed_at"), 0.0),
            "last_tested_at": None if _field(record, "last_tested_at") is None else _normalized_finite(_field(record, "last_tested_at"), 0.0),
            "supporting_evidence_ids": _string_list(_field(record, "supporting_evidence_ids")),
            "contradicting_evidence_ids": _string_list(_field(record, "contradicting_evidence_ids")),
            "source_type": _strict_text(_field(record, "source_type"), 64),
            "origin": origin,
        }
    if family == "episode":
        raw_event_id = _field(record, "source_event_id")
        if raw_event_id is None:
            event_id: str | int | None = None
        elif type(raw_event_id) is str:
            event_id = _strict_text(raw_event_id, 16000)
        elif type(raw_event_id) is int and not isinstance(raw_event_id, bool):
            event_id = raw_event_id
        else:
            raise AuthorizationError("event_id_type")
        return {
            "episode_id": _strict_text(_field(record, "episode_id"), 16000, allow_empty=False),
            "source_event_id": event_id,
            "simulation_timestamp": _normalized_finite(_field(record, "simulation_timestamp"), 0.0),
            "summary": _strict_text(_field(record, "summary"), 12000),
            "category": _strict_text(_field(record, "category"), 80),
            "salience": _normalized_finite(_field(record, "salience"), 0.5, minimum=0.0, maximum=1.0),
            "status": _strict_text(_field(record, "status"), 32),
            "linked_task_ids": _string_list(_field(record, "linked_task_ids")),
            "linked_note_ids": _string_list(_field(record, "linked_note_ids")),
            "linked_belief_ids": _string_list(_field(record, "linked_belief_ids")),
            "linked_marker_ids": _string_list(_field(record, "linked_marker_ids")),
            "linked_memory_ids": _string_list(_field(record, "linked_memory_ids")),
            "origin": origin,
        }
    raise AuthorizationError("unsupported_family")


def _memory_projection(record: Any) -> dict[str, Any]:
    def member(name: str) -> Any:
        if type(record) is dict:
            return record.get(name)
        from app.memory.vault import MemoryRecord

        if type(record) is MemoryRecord:
            return getattr(record, name, None)
        raise AuthorizationError("unsupported_memory_type")

    tags = member("tags")
    return {
        "id": _strict_text(member("id"), 160, allow_empty=False),
        "category": _strict_text(member("category"), 80),
        "title": _strict_text(member("title"), 240),
        "content": _strict_text(member("content"), 12000),
        "importance": _finite(member("importance"), minimum=0.0, maximum=1.0),
        "tags": _string_list(tags, maximum=512, text_maximum=12000),
        "created_at": _strict_text(member("created_at"), 160),
        "sim_time": _finite(member("sim_time")),
        "path": _strict_text(member("path"), 1000),
    }


def _strict_generic(value: Any, *, depth: int = 0, active: set[int] | None = None, nodes: list[int] | None = None) -> Any:
    if depth > MAX_GENERIC_DEPTH:
        raise AuthorizationError("generic_depth")
    if active is None:
        active = set()
    if nodes is None:
        nodes = [MAX_GENERIC_NODES]
    nodes[0] -= 1
    if nodes[0] < 0:
        raise AuthorizationError("generic_nodes")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise AuthorizationError("generic_nonfinite")
        return value
    if type(value) is str:
        if len(value) > 12000:
            raise AuthorizationError("generic_text")
        return value
    if type(value) is list:
        if len(value) > MAX_GENERIC_ITEMS:
            raise AuthorizationError("generic_items")
        identity = id(value)
        if identity in active:
            raise AuthorizationError("generic_cycle")
        active.add(identity)
        try:
            return [_strict_generic(item, depth=depth + 1, active=active, nodes=nodes) for item in value]
        finally:
            active.remove(identity)
    if type(value) is dict:
        if len(value) > MAX_GENERIC_ITEMS:
            raise AuthorizationError("generic_items")
        identity = id(value)
        if identity in active:
            raise AuthorizationError("generic_cycle")
        active.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str or len(key) > 240 or key in result:
                    raise AuthorizationError("generic_key")
                result[key] = _strict_generic(item, depth=depth + 1, active=active, nodes=nodes)
            return result
        finally:
            active.remove(identity)
    raise AuthorizationError("generic_type")


def _typed(value: Any) -> Any:
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise AuthorizationError("typed_nonfinite")
        return ["float", value.hex()]
    if type(value) is str:
        return ["string", len(value.encode("utf-8")), value]
    if type(value) is list:
        return ["list", len(value), [_typed(item) for item in value]]
    if type(value) is dict:
        ordered = [[key, _typed(value[key])] for key in sorted(value)]
        return ["map", len(ordered), ordered]
    raise AuthorizationError("typed_type")


def _encoded(payload: dict[str, Any]) -> bytes:
    return json.dumps(_typed(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _effective_key(key: bytes, epoch_id: str) -> bytes:
    return hmac.new(key, f"{AUTHORIZATION_DOMAIN}/key/v2\0{epoch_id}".encode("utf-8"), hashlib.sha256).digest()


def _digest(key: bytes, epoch_id: str, payload: dict[str, Any]) -> str:
    return hmac.new(_effective_key(key, epoch_id), _encoded(payload), hashlib.sha256).hexdigest()


def _default_epoch(key: bytes) -> str:
    return hashlib.sha256(b"embodied-alife-test-epoch\0" + key).hexdigest()[:32]


def _context_for_key(key: bytes) -> tuple[str, str, str]:
    return _KEY_CONTEXTS.get(key, (_default_epoch(key), "test-run", "test-world"))


def attach_key(
    agent: Any,
    key: bytes | None,
    *,
    epoch_id: str | None = None,
    run_id: str | None = None,
    world_generation_id: str | None = None,
) -> None:
    try:
        agent._ari_integrity_key = key
        if key is None:
            agent._ari_authority_epoch = None
            agent._ari_authority_run_id = None
            agent._ari_authority_world_generation_id = None
            return
        previous = _context_for_key(key)
        context = (
            epoch_id if type(epoch_id) is str and epoch_id else previous[0],
            run_id if type(run_id) is str and run_id else previous[1],
            world_generation_id if type(world_generation_id) is str and world_generation_id else previous[2],
        )
        agent._ari_authority_epoch, agent._ari_authority_run_id, agent._ari_authority_world_generation_id = context
        _KEY_CONTEXTS[key] = context
    except Exception:
        return


def agent_key(agent: Any) -> bytes | None:
    try:
        key = agent._ari_integrity_key
    except Exception:
        return None
    return key if type(key) is bytes and len(key) >= 32 else None


def authority_context(authority: Any = None, *, key: bytes | None = None) -> tuple[str, str, str] | None:
    try:
        if authority is not None:
            raw_key = agent_key(authority)
            epoch = authority._ari_authority_epoch
            run_id = authority._ari_authority_run_id
            world_id = authority._ari_authority_world_generation_id
            if raw_key is None or any(type(value) is not str or not value for value in (epoch, run_id, world_id)):
                return None
            return epoch, run_id, world_id
        if key is None or type(key) is not bytes or len(key) < 32:
            return None
        return _context_for_key(key)
    except Exception:
        return None


def current_epoch_id(runtime_dir: Path) -> str | None:
    path = runtime_dir / EPOCH_FILE_NAME
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if type(value) is not dict or value.get("schema_version") != 1:
        return None
    epoch = value.get("epoch_id")
    return epoch if type(epoch) is str and len(epoch) == 32 and all(ch in "0123456789abcdef" for ch in epoch) else None


def _write_epoch(runtime_dir: Path, epoch_id: str) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / EPOCH_FILE_NAME
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"schema_version": 1, "epoch_id": epoch_id}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_or_create_key(runtime_dir: Path, *, allow_create: bool) -> bytes | None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / KEY_FILE_NAME
    if path.is_file():
        try:
            raw = bytes.fromhex(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None
        if len(raw) < 32:
            return None
    else:
        if not allow_create:
            return None
        raw = secrets.token_bytes(32)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(raw.hex() + "\n", encoding="ascii")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(path)

    epoch_path = runtime_dir / EPOCH_FILE_NAME
    epoch = current_epoch_id(runtime_dir)
    if epoch is None:
        if epoch_path.exists():
            # Corrupt experiment evidence is never silently replaced.
            return None
        # Explicit migration for a valid pre-Post6 local key, or creation for a
        # fresh install. Version-1 proofs remain unauthorized.
        epoch = secrets.token_hex(16)
        _write_epoch(runtime_dir, epoch)
    _KEY_CONTEXTS[raw] = (epoch, "unbound-run", "unbound-world")
    return raw


def rotate_authority_epoch(runtime_dir: Path, key: bytes | None) -> str | None:
    if type(key) is not bytes or len(key) < 32:
        return None
    epoch = secrets.token_hex(16)
    _write_epoch(runtime_dir, epoch)
    previous = _context_for_key(key)
    _KEY_CONTEXTS[key] = (epoch, previous[1], previous[2])
    return epoch


def _record_identity(family: str, projection: dict[str, Any]) -> str:
    field = {
        "key_item": "key_item_id",
        "task": "task_id",
        "note": "note_id",
        "marker": "marker_id",
        "belief": "belief_id",
        "episode": "episode_id",
    }.get(family)
    if field is None:
        raise AuthorizationError("unsupported_family")
    return projection[field]


def record_payload(
    family: str,
    record: Any,
    *,
    creation_path: str | None = None,
    source_ref: str | None = None,
    authority: Any = None,
    key: bytes | None = None,
) -> dict[str, Any] | None:
    try:
        context = authority_context(authority, key=key)
        if context is None:
            return None
        epoch, run_id, world_id = context
        projection = _record_projection(family, record)
        path = creation_path if creation_path is not None else _provenance_field(record, "creation_path")
        reference = source_ref if source_ref is not None else _provenance_field(record, "source_id")
        return {
            "envelope_schema_version": PROOF_VERSION,
            "authorization_domain": AUTHORIZATION_DOMAIN,
            "record_family": family,
            "record_id": _record_identity(family, projection),
            "experiment_epoch": _strict_text(epoch, 64, allow_empty=False),
            "run_id": _strict_text(run_id, 160, allow_empty=False),
            "world_generation_id": _strict_text(world_id, 160, allow_empty=False),
            "creation_path": _strict_text(path, 80, allow_empty=False),
            "source_ref": _strict_text(reference or "", 240),
            "content": projection,
        }
    except Exception:
        return None


def seal_record(
    family: str,
    record: Any,
    key: bytes | None,
    creation_path: str,
    *,
    source_type: str | None = None,
    source_ref: str | None = None,
    authority: Any = None,
) -> bool:
    try:
        if type(key) is not bytes or len(key) < 32 or creation_path not in CONTROLLED_CREATION_PATHS:
            return False
        if source_type is not None:
            normalized_source = _strict_text(source_type, 80, allow_empty=False).lower()
            if normalized_source not in _ALLOWED_SOURCES.get(creation_path, set()):
                return False
            if not _set_provenance_value(record, "source_type", normalized_source):
                return False
        if source_ref is not None and not _set_provenance_value(record, "source_id", _strict_text(source_ref, 240)):
            return False
        if not _set_provenance_value(record, "creation_path", creation_path):
            return False
        if not _set_provenance_value(record, "proof_version", PROOF_VERSION):
            return False
        payload = record_payload(family, record, creation_path=creation_path, source_ref=source_ref, authority=authority, key=key)
        if payload is None:
            return False
        epoch = payload["experiment_epoch"]
        return _set_provenance_value(record, "proof", _digest(key, epoch, payload))
    except Exception:
        return False


def verify_record(family: str, record: Any, agent: Any) -> bool:
    try:
        key = agent_key(agent)
        context = authority_context(agent)
        if key is None or context is None:
            return False
        creation_path = _provenance_field(record, "creation_path")
        source_type = _provenance_field(record, "source_type")
        proof = _provenance_field(record, "proof")
        version = _provenance_field(record, "proof_version")
        if type(creation_path) is not str or creation_path not in CONTROLLED_CREATION_PATHS:
            return False
        if type(source_type) is not str or source_type.lower() not in _ALLOWED_SOURCES.get(creation_path, set()):
            return False
        if type(version) is not int or isinstance(version, bool) or version != PROOF_VERSION:
            return False
        if type(proof) is not str or len(proof) != 64 or any(ch not in "0123456789abcdef" for ch in proof):
            return False
        payload = record_payload(family, record, authority=agent)
        if payload is None:
            return False
        if family == "belief" and payload["content"]["source_type"].lower() != source_type.lower():
            return False
        expected = _digest(key, payload["experiment_epoch"], payload)
        return hmac.compare_digest(proof, expected)
    except Exception:
        return False


def _payload_envelope(agent: Any, family: str, value: Any, creation_path: str, source_ref: str) -> dict[str, Any]:
    context = authority_context(agent)
    if context is None:
        raise AuthorizationError("missing_context")
    epoch, run_id, world_id = context
    return {
        "envelope_schema_version": PROOF_VERSION,
        "authorization_domain": AUTHORIZATION_DOMAIN,
        "payload_family": _strict_text(family, 240, allow_empty=False),
        "experiment_epoch": _strict_text(epoch, 64, allow_empty=False),
        "run_id": _strict_text(run_id, 160, allow_empty=False),
        "world_generation_id": _strict_text(world_id, 160, allow_empty=False),
        "creation_path": _strict_text(creation_path, 80, allow_empty=False),
        "source_ref": _strict_text(source_ref, 240),
        "content": _strict_generic(value),
    }


def sign_payload(agent: Any, family: str, value: Any, creation_path: str, *, source_ref: str) -> dict[str, Any] | None:
    try:
        key = agent_key(agent)
        if key is None or creation_path not in CONTROLLED_CREATION_PATHS:
            return None
        payload = _payload_envelope(agent, family, value, creation_path, source_ref)
        proof = _digest(key, payload["experiment_epoch"], payload)
        return {
            "proof_version": PROOF_VERSION,
            "creation_path": creation_path,
            "source_ref": source_ref,
            "experiment_epoch": payload["experiment_epoch"],
            "run_id": payload["run_id"],
            "world_generation_id": payload["world_generation_id"],
            "proof": proof,
        }
    except Exception:
        return None


def verify_payload(agent: Any, family: str, value: Any, evidence: Any) -> bool:
    try:
        if type(evidence) is not dict:
            return False
        key = agent_key(agent)
        context = authority_context(agent)
        if key is None or context is None:
            return False
        creation_path = evidence.get("creation_path")
        source_ref = evidence.get("source_ref")
        proof = evidence.get("payload_proof") if "payload_proof" in evidence else evidence.get("proof")
        version = evidence.get("proof_version")
        if type(creation_path) is not str or creation_path not in CONTROLLED_CREATION_PATHS:
            return False
        if type(source_ref) is not str or len(source_ref) > 240:
            return False
        if type(version) is not int or isinstance(version, bool) or version != PROOF_VERSION:
            return False
        if type(proof) is not str or len(proof) != 64 or any(ch not in "0123456789abcdef" for ch in proof):
            return False
        epoch, run_id, world_id = context
        if evidence.get("experiment_epoch") != epoch or evidence.get("run_id") != run_id or evidence.get("world_generation_id") != world_id:
            return False
        payload = _payload_envelope(agent, family, value, creation_path, source_ref)
        return hmac.compare_digest(proof, _digest(key, epoch, payload))
    except Exception:
        return False


def _event_projection(event: Any) -> dict[str, Any]:
    if type(event) is not dict:
        raise AuthorizationError("event_type")
    data = event.get("data")
    if type(data) is not dict:
        raise AuthorizationError("event_data_type")
    clean_data = {key: value for key, value in data.items() if key != "_ari_integrity"}
    event_id = event.get("id")
    if type(event_id) is not int or isinstance(event_id, bool) or event_id <= 0:
        raise AuthorizationError("event_id")
    return {
        "event_id": event_id,
        "sequence_id": event_id,
        "event_type": _strict_text(event.get("kind"), 120, allow_empty=False),
        "sim_time": _finite(event.get("sim_time")),
        "importance": _finite(event.get("importance"), minimum=0.0, maximum=1.0),
        "message": _strict_text(event.get("message"), 4000),
        "run_id": _strict_text(event.get("run_id"), 160, allow_empty=False),
        "world_generation_id": _strict_text(event.get("world_generation_id"), 160, allow_empty=False),
        "authorization_epoch_id": _strict_text(event.get("authorization_epoch_id"), 64, allow_empty=False),
        "outcome": _strict_generic(clean_data),
    }


def sign_event(agent: Any, family: str, event: Any, creation_path: str, *, source_ref: str) -> dict[str, Any] | None:
    try:
        key = agent_key(agent)
        context = authority_context(agent)
        if key is None or context is None or creation_path not in CONTROLLED_CREATION_PATHS:
            return None
        epoch, run_id, world_id = context
        projection = _event_projection(event)
        if projection["authorization_epoch_id"] != epoch or projection["run_id"] != run_id or projection["world_generation_id"] != world_id:
            return None
        payload = {
            "envelope_schema_version": PROOF_VERSION,
            "authorization_domain": f"{AUTHORIZATION_DOMAIN}/event",
            "payload_family": _strict_text(family, 120, allow_empty=False),
            "experiment_epoch": epoch,
            "run_id": run_id,
            "world_generation_id": world_id,
            "creation_path": creation_path,
            "source_ref": _strict_text(source_ref, 240),
            "event": projection,
        }
        clean_data = projection["outcome"]
        payload_compat = _payload_envelope(agent, family, clean_data, creation_path, source_ref)
        return {
            "proof_version": PROOF_VERSION,
            "creation_path": creation_path,
            "source_ref": source_ref,
            "experiment_epoch": epoch,
            "run_id": run_id,
            "world_generation_id": world_id,
            "event_id": projection["event_id"],
            "payload_proof": _digest(key, epoch, payload_compat),
            "proof": _digest(key, epoch, payload),
        }
    except Exception:
        return None


def verify_event(agent: Any, family: str, event: Any, evidence: Any) -> bool:
    try:
        if type(evidence) is not dict:
            return False
        key = agent_key(agent)
        context = authority_context(agent)
        if key is None or context is None:
            return False
        epoch, run_id, world_id = context
        creation_path = evidence.get("creation_path")
        source_ref = evidence.get("source_ref")
        proof = evidence.get("proof")
        if evidence.get("proof_version") != PROOF_VERSION or creation_path not in CONTROLLED_CREATION_PATHS:
            return False
        if type(source_ref) is not str or len(source_ref) > 240 or type(proof) is not str or len(proof) != 64:
            return False
        if any(ch not in "0123456789abcdef" for ch in proof):
            return False
        projection = _event_projection(event)
        if (
            evidence.get("experiment_epoch") != epoch
            or evidence.get("run_id") != run_id
            or evidence.get("world_generation_id") != world_id
            or evidence.get("event_id") != projection["event_id"]
            or projection["authorization_epoch_id"] != epoch
            or projection["run_id"] != run_id
            or projection["world_generation_id"] != world_id
        ):
            return False
        payload = {
            "envelope_schema_version": PROOF_VERSION,
            "authorization_domain": f"{AUTHORIZATION_DOMAIN}/event",
            "payload_family": _strict_text(family, 120, allow_empty=False),
            "experiment_epoch": epoch,
            "run_id": run_id,
            "world_generation_id": world_id,
            "creation_path": creation_path,
            "source_ref": source_ref,
            "event": projection,
        }
        return hmac.compare_digest(proof, _digest(key, epoch, payload))
    except Exception:
        return False


def _knowledge_key(family: str, identity: str) -> str:
    if type(family) is not str or type(identity) is not str:
        return ""
    return f"{family[:48]}:{identity[:160]}"


def seal_knowledge(agent: Any, family: str, identity: str, value: Any, creation_path: str, *, source_ref: str = "") -> bool:
    try:
        proofs = agent.ari_knowledge_proofs
        if type(proofs) is not dict:
            return False
        key = _knowledge_key(family, identity)
        if not key:
            return False
        evidence = sign_payload(agent, f"knowledge:{family}:{identity}", value, creation_path, source_ref=source_ref)
        if evidence is None:
            return False
        proofs[key] = evidence
        return True
    except Exception:
        return False


def verify_knowledge(agent: Any, family: str, identity: str, value: Any) -> bool:
    try:
        proofs = agent.ari_knowledge_proofs
        if type(proofs) is not dict:
            return False
        evidence = proofs.get(_knowledge_key(family, identity))
        return verify_payload(agent, f"knowledge:{family}:{identity}", value, evidence)
    except Exception:
        return False


def state_contains_proofs(value: Any, *, budget: int = 5000) -> bool:
    seen: set[int] = set()

    def visit(current: Any, remaining: list[int]) -> bool:
        if remaining[0] <= 0:
            return False
        remaining[0] -= 1
        if type(current) is dict:
            identity = id(current)
            if identity in seen:
                return False
            seen.add(identity)
            try:
                proof = current.get("proof")
                if type(proof) is str and len(proof) == 64:
                    return True
                for index, item in enumerate(current.values()):
                    if index >= 512:
                        break
                    if visit(item, remaining):
                        return True
            finally:
                seen.discard(identity)
        elif type(current) is list:
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

    try:
        return visit(value, [budget])
    except Exception:
        return False


def _load_memory_ledger(runtime_dir: Path) -> dict[str, Any]:
    path = runtime_dir / MEMORY_LEDGER_NAME
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if type(value) is not dict:
        return {}
    result: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= MAX_LEDGER_ENTRIES:
            break
        if type(key) is str and type(item) is dict:
            result[key[:256]] = item
    return result


def _write_memory_ledger(runtime_dir: Path, ledger: dict[str, Any]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / MEMORY_LEDGER_NAME
    temporary = path.with_suffix(".tmp")
    bounded = dict(list(ledger.items())[-MAX_LEDGER_ENTRIES:])
    temporary.write_text(json.dumps(bounded, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _memory_identity(record: Any) -> str:
    return _memory_projection(record)["id"]


def _memory_payload(record: Any, creation_path: str, source_ref: str, context: tuple[str, str, str]) -> dict[str, Any]:
    epoch, run_id, world_id = context
    projection = _memory_projection(record)
    return {
        "envelope_schema_version": PROOF_VERSION,
        "authorization_domain": f"{AUTHORIZATION_DOMAIN}/durable-memory",
        "record_family": "durable_memory",
        "record_id": projection["id"],
        "experiment_epoch": epoch,
        "run_id": run_id,
        "world_generation_id": world_id,
        "creation_path": creation_path,
        "source_ref": source_ref,
        "content": projection,
    }


def seal_memory_record(
    runtime_dir: Path,
    record: Any,
    key: bytes | None,
    creation_path: str,
    *,
    source_ref: str,
    authority: Any = None,
) -> bool:
    try:
        if type(key) is not bytes or len(key) < 32 or creation_path not in {"validated_action_event", "validated_consolidation"}:
            return False
        context = authority_context(authority, key=key)
        if context is None:
            return False
        identity = _memory_identity(record)
        epoch, run_id, world_id = context
        payload = _memory_payload(record, creation_path, _strict_text(source_ref, 240), context)
        ledger = _load_memory_ledger(runtime_dir)
        ledger[f"{epoch}:{identity}"] = {
            "proof_version": PROOF_VERSION,
            "creation_path": creation_path,
            "source_ref": source_ref,
            "experiment_epoch": epoch,
            "run_id": run_id,
            "world_generation_id": world_id,
            "proof": _digest(key, epoch, payload),
        }
        _write_memory_ledger(runtime_dir, ledger)
        return True
    except Exception:
        return False


def verify_memory_record(runtime_dir: Path, record: Any, key: bytes | None, *, authority: Any = None) -> bool:
    try:
        if type(key) is not bytes or len(key) < 32:
            return False
        context = authority_context(authority, key=key)
        if context is None:
            return False
        epoch, run_id, world_id = context
        identity = _memory_identity(record)
        evidence = _load_memory_ledger(runtime_dir).get(f"{epoch}:{identity}")
        if type(evidence) is not dict:
            return False
        creation_path = evidence.get("creation_path")
        source_ref = evidence.get("source_ref")
        proof = evidence.get("proof")
        if creation_path not in {"validated_action_event", "validated_consolidation"}:
            return False
        if evidence.get("proof_version") != PROOF_VERSION:
            return False
        if evidence.get("experiment_epoch") != epoch or evidence.get("run_id") != run_id or evidence.get("world_generation_id") != world_id:
            return False
        if type(source_ref) is not str or type(proof) is not str or len(proof) != 64:
            return False
        payload = _memory_payload(record, creation_path, source_ref, context)
        return hmac.compare_digest(proof, _digest(key, epoch, payload))
    except Exception:
        return False


def safe_message(value: Any, limit: int = 4000) -> str:
    if type(value) is str:
        return value[:limit]
    if isinstance(value, bool):
        return "true" if value else "false"
    if type(value) is int:
        return str(value)[:limit]
    if type(value) is float and math.isfinite(value):
        return str(value)[:limit]
    return ""


def _same_record(family: str, left: Any, right: Any) -> bool:
    try:
        return _record_projection(family, left) == _record_projection(family, right)
    except Exception:
        return False


def seal_deterministic_starters(agent: Any, key: bytes | None) -> None:
    if key is None:
        return
    from app.simulation.cognition import starter_key_items, starter_tasks

    expected_items = starter_key_items()
    try:
        actual_items = agent.key_items
    except Exception:
        actual_items = None
    if type(actual_items) is dict:
        for identity, expected in expected_items.items():
            actual = actual_items.get(identity)
            if actual is not None and _same_record("key_item", actual, expected):
                seal_record(
                    "key_item",
                    actual,
                    key,
                    "deterministic_starter",
                    source_type="system_initialization",
                    source_ref="v0.4.0-starter-kit",
                    authority=agent,
                )

    expected_tasks = starter_tasks()
    try:
        actual_tasks = agent.tasks
    except Exception:
        actual_tasks = None
    if type(actual_tasks) is dict:
        for identity, expected in expected_tasks.items():
            actual = actual_tasks.get(identity)
            if actual is not None and _same_record("task", actual, expected):
                seal_record(
                    "task",
                    actual,
                    key,
                    "deterministic_starter",
                    source_type="system_initialization",
                    source_ref="v0.4.0-starter-journal",
                    authority=agent,
                )
