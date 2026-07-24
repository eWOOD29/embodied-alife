from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from app.serialization import finite_number, json_safe_dict
from app.simulation.belief_store import BeliefStore
from app.simulation.cognition import (
    AwakeningState,
    EpisodeRecord,
    KeyItem,
    MapMarker,
    NoteRecord,
    TaskRecord,
    starter_key_items,
    starter_tasks,
)


@dataclass(slots=True)
class InventoryItem:
    kind: str
    quantity: int = 1


def _scalar_text(value: Any, limit: int = 160) -> str:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)[:limit]
    return ""


def _load_records(value: Any, record_type: Any, id_field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    records: dict[str, Any] = {}
    for index, (key, raw) in enumerate(value.items()):
        if index >= 10000:
            break
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        identity = _scalar_text(raw.get(id_field) or key)
        if not identity:
            continue
        payload[id_field] = identity
        try:
            record = record_type.from_dict(payload)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        loaded_id = _scalar_text(getattr(record, id_field, ""))
        if loaded_id and loaded_id not in records:
            records[loaded_id] = record
    return records


def _mapping(value: Any, limit: int = 10000) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for index, (raw_key, raw_value) in enumerate(value.items()):
        if index >= limit:
            break
        key = _scalar_text(raw_key)
        if key:
            result[key] = raw_value
    return result


def _nested_mapping(value: Any, limit: int = 10000) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, raw in _mapping(value, limit).items():
        if isinstance(raw, dict):
            result[key] = dict(list(raw.items())[:1000])
    return result


def _text_mapping(value: Any, limit: int = 10000) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw in _mapping(value, limit).items():
        text = _scalar_text(raw, 4000)
        if text:
            result[key] = text
    return result


def _number_mapping(value: Any, limit: int = 1000) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, raw in _mapping(value, limit).items():
        number = finite_number(raw, None, minimum=-1_000_000.0, maximum=1_000_000.0)
        if number is not None:
            result[key] = number
    return result


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    if isinstance(value, (set, frozenset)):
        iterable = sorted(
            (raw for raw in value if isinstance(raw, (str, int)) and not isinstance(raw, bool)),
            key=lambda raw: (type(raw).__name__, raw),
        )
    else:
        iterable = value
    result: list[str] = []
    for raw in iterable:
        item = _scalar_text(raw, 4000)
        if item:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _record_list(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, dict):
            result.append(dict(list(raw.items())[:1000]))
        if len(result) >= limit:
            break
    return result


def _inventory(value: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(value, dict):
        return result
    for index, (raw_key, raw_quantity) in enumerate(value.items()):
        if index >= 1000:
            break
        key = _scalar_text(raw_key, 80)
        quantity = finite_number(raw_quantity, None, minimum=0.0, maximum=1_000_000.0)
        if key and quantity is not None:
            result[key] = int(quantity)
    return result


@dataclass(slots=True)
class AgentState:
    name: str = "Ari"
    x: float | None = 0.0
    y: float | None = 0.0
    facing: str = "north"
    movement_speed: float = 2.0
    collision_radius: float = 0.35
    health: float = 100.0
    energy: float = 78.0
    hunger: float = 18.0
    hydration: float = 82.0
    body_temperature_c: float = 37.0
    sleep_pressure: float = 12.0
    pain: float = 0.0
    injury: str | None = None
    inventory: dict[str, int] = field(default_factory=dict)
    inventory_capacity: int = 8
    key_items: dict[str, KeyItem] = field(default_factory=starter_key_items)
    tasks: dict[str, TaskRecord] = field(default_factory=starter_tasks)
    notes: dict[str, NoteRecord] = field(default_factory=dict)
    map_markers: dict[str, MapMarker] = field(default_factory=dict)
    beliefs: BeliefStore = field(default_factory=BeliefStore)
    short_term_episodes: dict[str, EpisodeRecord] = field(default_factory=dict)
    awakening: AwakeningState = field(default_factory=AwakeningState)
    cognition_schema_version: int = 1
    current_action: dict[str, Any] | None = None
    current_intention: str = "Understand what is around me."
    active_plan: list[str] = field(default_factory=list)
    known_locations: dict[str, dict[str, Any]] = field(default_factory=dict)
    explored: set[str] = field(default_factory=set)
    known_terrain: dict[str, str] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)
    personality_traits: dict[str, float] = field(
        default_factory=lambda: {"curiosity": 0.78, "caution": 0.61, "persistence": 0.67, "sociability": 0.42}
    )
    alive: bool = True
    sleeping: bool = False
    grace_seconds_remaining: float = 240.0
    last_damage_time: float = -1.0
    last_decision_reason: str = ""
    decision_source: str = "fallback"
    ari_knowledge_proofs: dict[str, dict[str, Any]] = field(default_factory=dict)
    _ari_integrity_key: bytes | None = field(default=None, repr=False, compare=False)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "beliefs" and not isinstance(value, BeliefStore):
            value = BeliefStore(value)
        object.__setattr__(self, name, value)

    @property
    def inventory_used(self) -> int:
        inventory = self.inventory if isinstance(self.inventory, dict) else {}
        return sum(quantity for quantity in inventory.values() if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0)

    def can_add(self, quantity: int = 1) -> bool:
        requested = quantity if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0 else 0
        capacity = finite_number(self.inventory_capacity, 0.0, minimum=0.0, maximum=1_000_000.0) or 0.0
        return self.inventory_used + requested <= int(capacity)

    def add_item(self, kind: str, quantity: int = 1) -> bool:
        key_items = self.key_items if isinstance(self.key_items, dict) else {}
        inventory = self.inventory if isinstance(self.inventory, dict) else {}
        if kind in key_items or not self.can_add(quantity):
            return False
        inventory[kind] = inventory.get(kind, 0) + quantity
        self.inventory = inventory
        return True

    def remove_item(self, kind: str, quantity: int = 1) -> bool:
        key_items = self.key_items if isinstance(self.key_items, dict) else {}
        inventory = self.inventory if isinstance(self.inventory, dict) else {}
        available = inventory.get(kind, 0)
        if kind in key_items or not isinstance(available, int) or isinstance(available, bool) or available < quantity:
            return False
        inventory[kind] -= quantity
        if inventory[kind] <= 0:
            del inventory[kind]
        self.inventory = inventory
        return True

    def to_dict(self) -> dict[str, Any]:
        data = {
            field_info.name: getattr(self, field_info.name)
            for field_info in fields(self)
            if not field_info.name.startswith("_")
        }
        explored = self.explored if isinstance(self.explored, (list, tuple, set, frozenset)) else []
        safe_explored = []
        for raw in explored:
            item = _scalar_text(raw)
            if item:
                safe_explored.append(item)
            if len(safe_explored) >= 10000:
                break
        data["explored"] = sorted(set(safe_explored))
        return json_safe_dict(
            data,
            max_depth=10,
            max_items=10000,
            max_text=4000,
            max_nodes=100000,
            max_source_items=120000,
        )

    @classmethod
    def from_dict(cls, data: Any) -> "AgentState":
        if not isinstance(data, dict):
            return cls()
        allowed = {field_info.name for field_info in fields(cls) if not field_info.name.startswith("_")}
        copied = {key: value for key, value in data.items() if key in allowed}
        defaults = cls()

        for name in ("name", "facing", "current_intention", "last_decision_reason", "decision_source"):
            if name in copied:
                copied[name] = _scalar_text(copied[name], 4000) or getattr(defaults, name)
        if "injury" in copied:
            copied["injury"] = _scalar_text(copied["injury"], 1000) or None
        for name in ("x", "y"):
            if name in copied:
                copied[name] = finite_number(copied[name], None)
        for name in (
            "movement_speed",
            "collision_radius",
            "health",
            "energy",
            "hunger",
            "hydration",
            "body_temperature_c",
            "sleep_pressure",
            "pain",
            "grace_seconds_remaining",
            "last_damage_time",
        ):
            if name in copied:
                copied[name] = finite_number(copied[name], getattr(defaults, name))
        if "inventory_capacity" in copied:
            capacity = finite_number(copied["inventory_capacity"], float(defaults.inventory_capacity), minimum=0.0, maximum=1_000_000.0)
            copied["inventory_capacity"] = int(capacity if capacity is not None else defaults.inventory_capacity)
        for name in ("alive", "sleeping"):
            if name in copied:
                copied[name] = copied[name] if isinstance(copied[name], bool) else getattr(defaults, name)

        copied["explored"] = set(_string_list(copied.get("explored", []), 10000))
        copied["inventory"] = _inventory(copied.get("inventory"))

        raw_key_items = copied.get("key_items") if "key_items" in copied else None
        copied["key_items"] = starter_key_items() if "key_items" not in copied else _load_records(raw_key_items, KeyItem, "key_item_id")
        raw_tasks = copied.get("tasks") if "tasks" in copied else None
        copied["tasks"] = starter_tasks() if "tasks" not in copied else _load_records(raw_tasks, TaskRecord, "task_id")
        copied["notes"] = _load_records(copied.get("notes"), NoteRecord, "note_id")
        copied["map_markers"] = _load_records(copied.get("map_markers"), MapMarker, "marker_id")
        copied["beliefs"] = BeliefStore(copied.get("beliefs"))
        copied["short_term_episodes"] = _load_records(copied.get("short_term_episodes"), EpisodeRecord, "episode_id")
        copied["awakening"] = AwakeningState.from_dict(copied.get("awakening"))

        copied["known_locations"] = _nested_mapping(copied.get("known_locations"))
        copied["known_terrain"] = _text_mapping(copied.get("known_terrain"))
        copied["personality_traits"] = _number_mapping(copied.get("personality_traits"), 1000)
        copied["ari_knowledge_proofs"] = _nested_mapping(copied.get("ari_knowledge_proofs"), 20000)
        copied["current_action"] = dict(list(copied["current_action"].items())[:1000]) if isinstance(copied.get("current_action"), dict) else None
        copied["active_plan"] = _string_list(copied.get("active_plan"), 1000)
        copied["recent_events"] = _record_list(copied.get("recent_events"), 1000)
        copied["retrieved_memories"] = _record_list(copied.get("retrieved_memories"), 1000)
        version = finite_number(copied.get("cognition_schema_version", 1), 1.0, minimum=1.0, maximum=1_000_000.0)
        copied["cognition_schema_version"] = int(version if version is not None else 1)
        return cls(**copied)
