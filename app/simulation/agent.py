from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from app.serialization import json_safe_dict
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


def _load_records(value: Any, record_type: Any, id_field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        return {}
    records: dict[str, Any] = {}
    for key, raw in value.items():
        if not isinstance(raw, dict):
            continue
        try:
            record = record_type.from_dict({id_field: str(raw.get(id_field) or key), **raw})
        except (KeyError, TypeError, ValueError):
            continue
        records[str(getattr(record, id_field))] = record
    return records


@dataclass(slots=True)
class AgentState:
    name: str = "Ari"
    x: float = 0.0
    y: float = 0.0
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

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "beliefs" and not isinstance(value, BeliefStore):
            value = BeliefStore(value)
        object.__setattr__(self, name, value)

    @property
    def inventory_used(self) -> int:
        return sum(self.inventory.values())

    def can_add(self, quantity: int = 1) -> bool:
        return self.inventory_used + quantity <= self.inventory_capacity

    def add_item(self, kind: str, quantity: int = 1) -> bool:
        if kind in self.key_items or not self.can_add(quantity):
            return False
        self.inventory[kind] = self.inventory.get(kind, 0) + quantity
        return True

    def remove_item(self, kind: str, quantity: int = 1) -> bool:
        if kind in self.key_items or self.inventory.get(kind, 0) < quantity:
            return False
        self.inventory[kind] -= quantity
        if self.inventory[kind] <= 0:
            del self.inventory[kind]
        return True

    def to_dict(self) -> dict[str, Any]:
        # Read fields directly rather than using dataclasses.asdict(), which deep-copies
        # arbitrary mutated state before the bounded serializer can detect cycles.
        data = {field_info.name: getattr(self, field_info.name) for field_info in fields(self)}
        explored = self.explored if isinstance(self.explored, (list, tuple, set)) else []
        data["explored"] = sorted((str(item)[:160] for item in explored), key=str)[:10000]
        return json_safe_dict(data, max_depth=10, max_items=10000, max_text=4000, max_nodes=100000)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        copied = dict(data)
        explored = copied.get("explored", [])
        copied["explored"] = {str(item)[:160] for item in explored} if isinstance(explored, (list, tuple, set)) else set()
        raw_key_items = copied.get("key_items") if "key_items" in copied else None
        copied["key_items"] = starter_key_items() if "key_items" not in copied else _load_records(raw_key_items, KeyItem, "key_item_id")
        raw_tasks = copied.get("tasks") if "tasks" in copied else None
        copied["tasks"] = starter_tasks() if "tasks" not in copied else _load_records(raw_tasks, TaskRecord, "task_id")
        copied["notes"] = _load_records(copied.get("notes"), NoteRecord, "note_id")
        copied["map_markers"] = _load_records(copied.get("map_markers"), MapMarker, "marker_id")
        copied["beliefs"] = BeliefStore(copied.get("beliefs"))
        copied["short_term_episodes"] = _load_records(copied.get("short_term_episodes"), EpisodeRecord, "episode_id")
        copied["awakening"] = AwakeningState.from_dict(copied.get("awakening"))
        try:
            copied["cognition_schema_version"] = int(copied.get("cognition_schema_version", 1))
        except (TypeError, ValueError, OverflowError):
            copied["cognition_schema_version"] = 1
        return cls(**copied)
