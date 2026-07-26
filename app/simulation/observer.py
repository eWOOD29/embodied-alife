from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from app.serialization import finite_number, json_safe, json_safe_dict
from app.simulation.agent import AgentState
from app.simulation.perception import build_perception
from app.simulation.safe_state import builtin_dict_copy, builtin_dict_get, builtin_sequence, builtin_tail
from app.simulation.world import WorldState

OBSERVER_RECORD_LIMIT = 4096
OBSERVER_EVENT_LIMIT = 120
OBSERVER_MEMORY_LIMIT = 60
OBSERVER_SNAPSHOT_LIMIT = 200


def _member(value: Any, name: str, default: Any = None) -> Any:
    try:
        if issubclass(type(value), dict):
            return builtin_dict_get(value, name, default)
        return getattr(value, name, default)
    except Exception:
        return default


def _text(value: Any, limit: int = 4000) -> str:
    if type(value) is str:
        text = value.replace("\x00", "").strip()
    elif type(value) is int:
        text = str(value)
    elif type(value) is float:
        number = finite_number(value)
        text = "" if number is None else str(number)
    elif type(value) is bool:
        text = "true" if value else "false"
    else:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _number(value: Any, default: float | None = None, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    return finite_number(value, default, minimum=minimum, maximum=maximum)


def _mapping(value: Any) -> dict[Any, Any]:
    return builtin_dict_copy(value, limit=OBSERVER_RECORD_LIMIT)


def _tail(value: Any, limit: int) -> list[Any]:
    return builtin_tail(value, limit=max(1, limit), scan_limit=OBSERVER_RECORD_LIMIT)


def _safe_call(value: Any, method: str) -> Any:
    try:
        function = getattr(value, method)
        return function()
    except Exception:
        return None


def _record_projection(value: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if value is None:
        return None
    result: dict[str, Any] = {}
    for name in fields:
        raw = _member(value, name)
        if name in {"x", "y", "quantity", "quality", "nutrition", "energy", "last_harvest_time", "last_update_time"}:
            result[name] = _number(raw)
        elif name in {"portable", "edible", "dangerous"}:
            result[name] = raw is True
        else:
            text = _text(raw, 1000)
            if text:
                result[name] = text
    identity = result.get("id") or result.get("shelter_id")
    if not identity:
        return None
    metadata = _member(value, "metadata")
    if issubclass(type(metadata), dict):
        result["metadata"] = json_safe_dict(metadata, max_depth=5, max_items=64, max_text=1000, max_nodes=512, max_source_items=1024)
    return result


def _resources(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, resource in enumerate(_mapping(value).values()):
        if index >= OBSERVER_RECORD_LIMIT:
            break
        quantity = _number(_member(resource, "quantity"))
        if quantity is None or quantity <= 0:
            continue
        item = _record_projection(
            resource,
            ("id", "kind", "x", "y", "quantity", "portable", "edible", "nutrition", "energy", "last_harvest_time"),
        )
        if item is not None:
            result.append(item)
    return result


def _shelters(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, shelter in enumerate(_mapping(value).values()):
        if index >= OBSERVER_RECORD_LIMIT:
            break
        item = _record_projection(shelter, ("id", "shelter_id", "x", "y", "quality"))
        if item is not None:
            result.append(item)
    return result


def _npcs(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, npc in enumerate(_mapping(value).values()):
        if index >= OBSERVER_RECORD_LIMIT:
            break
        item = _record_projection(npc, ("id", "kind", "x", "y", "state", "dangerous", "health", "energy"))
        if item is not None:
            result.append(item)
    return result


def _safe_records(value: Any, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in builtin_sequence(value, limit=limit):
        if issubclass(type(record), dict):
            projected = json_safe_dict(record, max_depth=8, max_items=128, max_text=4000, max_nodes=2048, max_source_items=4096)
        elif is_dataclass(record) and not isinstance(record, type):
            projected = json_safe_dict(record, max_depth=8, max_items=128, max_text=4000, max_nodes=2048, max_source_items=4096)
        else:
            projected = {}
        if projected:
            result.append(projected)
    return result


def _agent_projection(agent: Any) -> dict[str, Any]:
    if type(agent) is AgentState:
        try:
            raw = agent.to_dict()
        except Exception:
            raw = None
        if type(raw) is dict:
            return json_safe_dict(raw, max_depth=10, max_items=10000, max_text=4000, max_nodes=100000, max_source_items=120000)
    fields = (
        "name", "x", "y", "facing", "health", "energy", "hunger", "hydration",
        "body_temperature_c", "sleep_pressure", "pain", "injury", "inventory", "inventory_capacity",
        "current_action", "current_intention", "active_plan", "alive", "sleeping",
    )
    return json_safe_dict({name: _member(agent, name) for name in fields}, max_depth=8, max_items=1000, max_text=4000, max_nodes=10000, max_source_items=20000)


def _world_projection(world: Any, *, include_map: bool) -> dict[str, Any]:
    if type(world) is WorldState:
        try:
            hour = _number(world.hour())
        except Exception:
            hour = None
        try:
            daylight = _number(world.daylight())
        except Exception:
            daylight = None
    else:
        hour = None
        daylight = None
    result = {
        "seed": _number(_member(world, "seed"), 0.0),
        "size": _number(_member(world, "size"), 0.0, minimum=0.0, maximum=1_000_000.0),
        "sim_time": _number(_member(world, "sim_time"), 0.0),
        "day": _number(_member(world, "day"), 0.0),
        "hour": hour,
        "daylight": daylight,
        "weather": _text(_member(world, "weather"), 160),
        "ambient_temperature_c": _number(_member(world, "ambient_temperature_c"), 0.0),
        "resources": _resources(_member(world, "resources")),
        "shelters": _shelters(_member(world, "shelters")),
        "npcs": _npcs(_member(world, "npcs")),
        "truth": json_safe_dict(_member(world, "truth_notes"), max_depth=8, max_items=1000, max_text=4000, max_nodes=20000, max_source_items=40000),
    }
    if include_map:
        result["tiles"] = json_safe(_member(world, "tiles"), max_depth=4, max_items=10000, max_text=160, max_nodes=200000, max_source_items=220000)
    return result


def build_observer_state(engine: Any, *, include_map: bool = False) -> dict[str, Any]:
    world = _member(engine, "world")
    agent = _member(engine, "agent")
    try:
        perception = build_perception(world, agent)
    except Exception:
        perception = {"available_actions": ["wait"], "position_known": False, "projection_error": "malformed_state_omitted"}

    try:
        memories_source = engine.vault.list_records(limit=OBSERVER_MEMORY_LIMIT, scan_limit=OBSERVER_RECORD_LIMIT)
    except TypeError:
        try:
            memories_source = _tail(engine.vault.list_records(), OBSERVER_MEMORY_LIMIT)
        except Exception:
            memories_source = []
    except Exception:
        memories_source = []

    try:
        snapshots_source = engine.snapshots.list()
    except Exception:
        snapshots_source = []

    status = _member(_member(engine, "brain"), "status")
    state = {
        "version": _number(_member(engine, "_state_version"), 0.0),
        "run_id": _text(_member(engine, "run_id"), 160),
        "world_generation_id": _text(_member(engine, "world_generation_id"), 160),
        "paused": _member(engine, "paused") is True,
        "speed": _number(_member(engine, "speed"), 1.0, minimum=0.0, maximum=1000.0),
        "world": _world_projection(world, include_map=include_map),
        "agent": _agent_projection(agent),
        "agent_perception": perception,
        "agent_beliefs": json_safe_dict(_member(agent, "beliefs"), max_depth=8, max_items=4096, max_text=4000, max_nodes=50000, max_source_items=60000),
        "last_decision": json_safe(_member(engine, "last_decision"), max_depth=8, max_items=256, max_text=4000, max_nodes=5000, max_source_items=10000),
        "last_action_result": json_safe(_member(engine, "last_action_result"), max_depth=8, max_items=256, max_text=4000, max_nodes=5000, max_source_items=10000),
        "pending_memory": json_safe(_member(engine, "pending_memory"), max_depth=8, max_items=256, max_text=4000, max_nodes=5000, max_source_items=10000),
        "events": _safe_records(_tail(_member(engine, "events"), OBSERVER_EVENT_LIMIT), OBSERVER_EVENT_LIMIT),
        "memory_writes": _safe_records(_tail(_member(engine, "memory_writes"), OBSERVER_MEMORY_LIMIT), OBSERVER_MEMORY_LIMIT),
        "memories": _safe_records(memories_source, OBSERVER_MEMORY_LIMIT),
        "model_status": json_safe_dict(status, max_depth=6, max_items=256, max_text=2000, max_nodes=4000, max_source_items=8000),
        "snapshots": _safe_records(snapshots_source, OBSERVER_SNAPSHOT_LIMIT),
    }
    return json_safe_dict(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=250000, max_source_items=300000)
