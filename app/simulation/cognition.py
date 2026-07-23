from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

COGNITION_SCHEMA_VERSION = 1
AWAKENING_NARRATIVE = (
    "I wake beneath an unfamiliar sky with no memory of how I arrived. My body feels real, vulnerable, and entirely my responsibility. "
    "I do not know this land, what lives here, or whether anyone else is nearby.\n\n"
    "I have only a few possessions: a blank map, a task journal, and a field notebook. The journal contains a handful of basic survival reminders—"
    "find water, secure food, and establish somewhere safe to rest—but what I do beyond that is up to me.\n\n"
    "If I am going to survive here, and perhaps eventually build a life worth living, I should begin by understanding my situation. "
    "The map and task journal may be the best place to start."
)


class TaskStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class NoteStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MarkerStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


class BeliefStatus(StrEnum):
    HYPOTHESIS = "hypothesis"
    WORKING = "working"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class EpisodeStatus(StrEnum):
    RECENT = "recent"
    SUMMARIZED = "summarized"
    EXPIRED = "expired"


@dataclass(slots=True)
class Provenance:
    source_type: str
    source_id: str | None = None
    detail: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None, *, default_source: str = "system_initialization") -> "Provenance":
        value = value or {}
        return cls(
            source_type=str(value.get("source_type") or default_source),
            source_id=value.get("source_id"),
            detail=value.get("detail"),
        )


@dataclass(slots=True)
class KeyItem:
    key_item_id: str
    display_name: str
    description: str
    provenance: Provenance

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KeyItem":
        return cls(
            key_item_id=str(value["key_item_id"]),
            display_name=str(value["display_name"]),
            description=str(value.get("description", "")),
            provenance=Provenance.from_dict(value.get("provenance")),
        )


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    title: str
    description: str
    created_by: str
    status: str
    priority: int
    created_at: float
    updated_at: float
    parent_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    linked_marker_ids: list[str] = field(default_factory=list)
    linked_note_ids: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=lambda: Provenance("system_initialization"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskRecord":
        return cls(
            task_id=str(value["task_id"]),
            title=str(value["title"]),
            description=str(value.get("description", "")),
            created_by=str(value.get("created_by", "system_initialization")),
            status=str(value.get("status", TaskStatus.PROPOSED.value)),
            priority=int(value.get("priority", 0)),
            created_at=float(value.get("created_at", 0.0)),
            updated_at=float(value.get("updated_at", value.get("created_at", 0.0))),
            parent_task_id=value.get("parent_task_id"),
            metadata=dict(value.get("metadata") or {}),
            linked_marker_ids=list(value.get("linked_marker_ids") or []),
            linked_note_ids=list(value.get("linked_note_ids") or []),
            provenance=Provenance.from_dict(value.get("provenance")),
        )


@dataclass(slots=True)
class NoteRecord:
    note_id: str
    title: str
    content: str
    tags: list[str]
    status: str
    created_at: float
    updated_at: float
    linked_task_ids: list[str] = field(default_factory=list)
    linked_marker_ids: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=lambda: Provenance("system_initialization"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NoteRecord":
        return cls(
            note_id=str(value["note_id"]),
            title=str(value.get("title", "Untitled note")),
            content=str(value.get("content", "")),
            tags=list(value.get("tags") or []),
            status=str(value.get("status", NoteStatus.ACTIVE.value)),
            created_at=float(value.get("created_at", 0.0)),
            updated_at=float(value.get("updated_at", value.get("created_at", 0.0))),
            linked_task_ids=list(value.get("linked_task_ids") or []),
            linked_marker_ids=list(value.get("linked_marker_ids") or []),
            provenance=Provenance.from_dict(value.get("provenance")),
        )


@dataclass(slots=True)
class MapMarker:
    marker_id: str
    label: str
    marker_type: str
    believed_location: dict[str, Any] | None
    confidence: float
    status: str
    notes: str
    created_at: float
    updated_at: float
    linked_task_ids: list[str] = field(default_factory=list)
    linked_note_ids: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=lambda: Provenance("perception"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MapMarker":
        return cls(
            marker_id=str(value["marker_id"]),
            label=str(value.get("label", "Unknown marker")),
            marker_type=str(value.get("marker_type", "unknown")),
            believed_location=dict(value["believed_location"]) if value.get("believed_location") is not None else None,
            confidence=float(value.get("confidence", 0.0)),
            status=str(value.get("status", MarkerStatus.ACTIVE.value)),
            notes=str(value.get("notes", "")),
            created_at=float(value.get("created_at", 0.0)),
            updated_at=float(value.get("updated_at", value.get("created_at", 0.0))),
            linked_task_ids=list(value.get("linked_task_ids") or []),
            linked_note_ids=list(value.get("linked_note_ids") or []),
            provenance=Provenance.from_dict(value.get("provenance"), default_source="perception"),
        )


@dataclass(slots=True)
class BeliefRecord:
    belief_id: str
    claim: str
    confidence: float
    basis: str
    status: str
    first_formed_at: float
    last_tested_at: float | None
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    source_type: str = "inference"
    provenance: Provenance = field(default_factory=lambda: Provenance("inference"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BeliefRecord":
        return cls(
            belief_id=str(value["belief_id"]),
            claim=str(value.get("claim", "")),
            confidence=float(value.get("confidence", 0.5)),
            basis=str(value.get("basis", "")),
            status=str(value.get("status", BeliefStatus.HYPOTHESIS.value)),
            first_formed_at=float(value.get("first_formed_at", 0.0)),
            last_tested_at=float(value["last_tested_at"]) if value.get("last_tested_at") is not None else None,
            supporting_evidence_ids=list(value.get("supporting_evidence_ids") or []),
            contradicting_evidence_ids=list(value.get("contradicting_evidence_ids") or []),
            source_type=str(value.get("source_type", "inference")),
            provenance=Provenance.from_dict(value.get("provenance"), default_source=str(value.get("source_type", "inference"))),
        )


@dataclass(slots=True)
class EpisodeRecord:
    episode_id: str
    source_event_id: str | int | None
    simulation_timestamp: float
    summary: str
    category: str
    salience: float
    status: str
    linked_task_ids: list[str] = field(default_factory=list)
    linked_note_ids: list[str] = field(default_factory=list)
    linked_belief_ids: list[str] = field(default_factory=list)
    linked_marker_ids: list[str] = field(default_factory=list)
    linked_memory_ids: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=lambda: Provenance("event"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EpisodeRecord":
        return cls(
            episode_id=str(value["episode_id"]),
            source_event_id=value.get("source_event_id"),
            simulation_timestamp=float(value.get("simulation_timestamp", 0.0)),
            summary=str(value.get("summary", "")),
            category=str(value.get("category", "general")),
            salience=float(value.get("salience", 0.5)),
            status=str(value.get("status", EpisodeStatus.RECENT.value)),
            linked_task_ids=list(value.get("linked_task_ids") or []),
            linked_note_ids=list(value.get("linked_note_ids") or []),
            linked_belief_ids=list(value.get("linked_belief_ids") or []),
            linked_marker_ids=list(value.get("linked_marker_ids") or []),
            linked_memory_ids=list(value.get("linked_memory_ids") or []),
            provenance=Provenance.from_dict(value.get("provenance"), default_source="event"),
        )


@dataclass(slots=True)
class AwakeningState:
    narrative: str = AWAKENING_NARRATIVE
    presented: bool = False
    presented_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AwakeningState":
        value = value or {}
        return cls(
            narrative=str(value.get("narrative") or AWAKENING_NARRATIVE),
            presented=bool(value.get("presented", False)),
            presented_at=float(value["presented_at"]) if value.get("presented_at") is not None else None,
        )


def starter_key_items() -> dict[str, KeyItem]:
    source = Provenance("system_initialization", detail="v0.4.0 starter kit")
    return {
        "blank_field_map": KeyItem("blank_field_map", "Blank Field Map", "A blank field map for recording Ari's own knowledge.", source),
        "task_journal": KeyItem("task_journal", "Task Journal", "A journal containing broad survival reminders.", source),
        "field_notebook": KeyItem("field_notebook", "Field Notebook", "A notebook for Ari's own observations and notes.", source),
    }


def starter_tasks(sim_time: float = 0.0) -> dict[str, TaskRecord]:
    titles = [
        "Assess my immediate surroundings.",
        "Find a reliable source of water.",
        "Secure enough food for the near future.",
        "Find or create a safe place to rest.",
    ]
    result: dict[str, TaskRecord] = {}
    for priority, title in enumerate(titles, start=1):
        task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"embodied-alife:v0.4.0:starter-task:{priority}"))
        result[task_id] = TaskRecord(
            task_id=task_id,
            title=title,
            description="A broad starter reminder, not a mandatory quest or claim about hidden world state.",
            created_by="starter_journal",
            status=TaskStatus.PROPOSED.value,
            priority=priority,
            created_at=sim_time,
            updated_at=sim_time,
            provenance=Provenance("system_initialization", source_id="v0.4.0-starter-journal"),
        )
    return result


def migrate_legacy_beliefs(value: Any, sim_time: float = 0.0) -> dict[str, BeliefRecord]:
    if not value:
        return {}
    migrated: dict[str, BeliefRecord] = {}
    if isinstance(value, dict):
        for key, raw in value.items():
            if isinstance(raw, dict) and "claim" in raw:
                record = BeliefRecord.from_dict({"belief_id": str(raw.get("belief_id") or key), **raw})
            else:
                record = BeliefRecord(
                    belief_id=str(key),
                    claim=str(raw),
                    confidence=0.5,
                    basis="Migrated from the pre-v0.4.0 subjective belief dictionary.",
                    status=BeliefStatus.WORKING.value,
                    first_formed_at=sim_time,
                    last_tested_at=None,
                    source_type="memory",
                    provenance=Provenance("legacy_migration", source_id=str(key)),
                )
            migrated[record.belief_id] = record
    elif isinstance(value, list):
        for raw in value:
            if isinstance(raw, dict):
                record = BeliefRecord.from_dict(raw)
                migrated[record.belief_id] = record
    return migrated
