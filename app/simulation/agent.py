from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.simulation.cognition import (
    AwakeningState,
    BeliefRecord,
    EpisodeRecord,
    KeyItem,
    MapMarker,
    NoteRecord,
    TaskRecord,
    migrate_legacy_beliefs,
    starter_key_items,
    starter_tasks,
)


@dataclass(slots=True)
class InventoryItem:
    kind: str
    quantity: int = 1


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
    beliefs: dict[str, BeliefRecord] = field(default_factory=dict)
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
        data = asdict(self)
        data["explored"] = sorted(self.explored)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        copied = dict(data)
        copied["explored"] = set(copied.get("explored", []))
        raw_key_items = copied.get("key_items")
        copied["key_items"] = (
            {
                key: KeyItem.from_dict({"key_item_id": key, **value})
                for key, value in raw_key_items.items()
            }
            if isinstance(raw_key_items, dict) and raw_key_items
            else starter_key_items()
        )
        raw_tasks = copied.get("tasks")
        copied["tasks"] = (
            {
                key: TaskRecord.from_dict({"task_id": key, **value})
                for key, value in raw_tasks.items()
            }
            if isinstance(raw_tasks, dict) and raw_tasks
            else starter_tasks()
        )
        copied["notes"] = {
            key: NoteRecord.from_dict({"note_id": key, **value})
            for key, value in (copied.get("notes") or {}).items()
        }
        copied["map_markers"] = {
            key: MapMarker.from_dict({"marker_id": key, **value})
            for key, value in (copied.get("map_markers") or {}).items()
        }
        copied["beliefs"] = migrate_legacy_beliefs(copied.get("beliefs"), sim_time=0.0)
        copied["short_term_episodes"] = {
            key: EpisodeRecord.from_dict({"episode_id": key, **value})
            for key, value in (copied.get("short_term_episodes") or {}).items()
        }
        copied["awakening"] = AwakeningState.from_dict(copied.get("awakening"))
        copied["cognition_schema_version"] = int(copied.get("cognition_schema_version", 1))
        return cls(**copied)
