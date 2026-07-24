from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

COGNITION_SCHEMA_VERSION = 1


TEXT_ID_LIMIT = 160
LINKED_ID_LIMIT = 32


def _number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        number = default
    else:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = default
    if not math.isfinite(number):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, float(default), minimum=-1_000_000_000, maximum=1_000_000_000))


def _bounded(value: Any, default: float = 0.5) -> float:
    return _number(value, default, minimum=0.0, maximum=1.0)


def _text(value: Any, default: str = "", limit: int = TEXT_ID_LIMIT) -> str:
    if not isinstance(value, (str, int, float, bool)):
        return default
    text = str(value).strip()
    if not text:
        return default
    return text if len(text) <= limit else text[:limit]


def _status(value: Any, enum_type: type[StrEnum], default: StrEnum) -> str:
    candidate = str(value or default.value)
    allowed = {item.value for item in enum_type}
    return candidate if candidate in allowed else default.value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, set):
        return sorted(value, key=lambda item: str(item))
    return list(value) if isinstance(value, (list, tuple)) else []


def _string_list(value: Any, *, allow_scalar: bool = True, count_limit: int = LINKED_ID_LIMIT, text_limit: int = TEXT_ID_LIMIT) -> list[str]:
    if allow_scalar and isinstance(value, (str, int)) and not isinstance(value, bool):
        source = [value]
    else:
        source = _list(value)
    result: list[str] = []
    for raw in source:
        if isinstance(raw, (list, tuple, set, dict)) or raw is None or isinstance(raw, bool):
            continue
        item = _text(raw, limit=text_limit)
        if item and item not in result:
            result.append(item)
        if len(result) >= count_limit:
            break
    return result
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
    creation_path: str | None = None
    proof_version: int | None = None
    proof: str | None = None

    @classmethod
    def from_dict(cls, value: Any, *, default_source: str = "unknown") -> "Provenance":
        value = value if isinstance(value, dict) else {}
        proof_version = value.get("proof_version")
        try:
            parsed_version = int(proof_version) if proof_version is not None and not isinstance(proof_version, bool) else None
        except (TypeError, ValueError, OverflowError):
            parsed_version = None
        proof = _text(value.get("proof"), limit=128) or None
        return cls(
            source_type=_text(value.get("source_type"), default_source, 64),
            source_id=_text(value.get("source_id"), limit=160) or None,
            detail=_text(value.get("detail"), limit=240) or None,
            creation_path=_text(value.get("creation_path"), limit=80) or None,
            proof_version=parsed_version,
            proof=proof,
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
            key_item_id=_text(value.get("key_item_id"), limit=160),
            display_name=_text(value.get("display_name"), "Unnamed key item", 160),
            description=_text(value.get("description"), limit=1000),
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
    provenance: Provenance = field(default_factory=lambda: Provenance("unknown"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskRecord":
        return cls(
            task_id=_text(value.get("task_id"), limit=160),
            title=_text(value.get("title"), "Untitled task", 240),
            description=_text(value.get("description"), limit=1000),
            created_by=_text(value.get("created_by"), "system_initialization", 80),
            status=_status(value.get("status"), TaskStatus, TaskStatus.PROPOSED),
            priority=_integer(value.get("priority", 0)),
            created_at=_number(value.get("created_at", 0.0)),
            updated_at=_number(value.get("updated_at", value.get("created_at", 0.0))),
            parent_task_id=value.get("parent_task_id"),
            metadata=_dict(value.get("metadata")),
            linked_marker_ids=_string_list(value.get("linked_marker_ids")),
            linked_note_ids=_string_list(value.get("linked_note_ids")),
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
    provenance: Provenance = field(default_factory=lambda: Provenance("unknown"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NoteRecord":
        return cls(
            note_id=_text(value.get("note_id"), limit=160),
            title=_text(value.get("title"), "Untitled note", 240),
            content=_text(value.get("content"), limit=4000),
            tags=_string_list(value.get("tags"), count_limit=32, text_limit=80),
            status=_status(value.get("status"), NoteStatus, NoteStatus.ACTIVE),
            created_at=_number(value.get("created_at", 0.0)),
            updated_at=_number(value.get("updated_at", value.get("created_at", 0.0))),
            linked_task_ids=_string_list(value.get("linked_task_ids")),
            linked_marker_ids=_string_list(value.get("linked_marker_ids")),
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
    provenance: Provenance = field(default_factory=lambda: Provenance("unknown"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MapMarker":
        return cls(
            marker_id=_text(value.get("marker_id"), limit=160),
            label=_text(value.get("label"), "Unknown marker", 240),
            marker_type=_text(value.get("marker_type"), "unknown", 80),
            believed_location=_dict(value.get("believed_location")) or None,
            confidence=_bounded(value.get("confidence"), 0.0),
            status=_status(value.get("status"), MarkerStatus, MarkerStatus.ACTIVE),
            notes=_text(value.get("notes"), limit=2000),
            created_at=_number(value.get("created_at", 0.0)),
            updated_at=_number(value.get("updated_at", value.get("created_at", 0.0))),
            linked_task_ids=_string_list(value.get("linked_task_ids")),
            linked_note_ids=_string_list(value.get("linked_note_ids")),
            provenance=Provenance.from_dict(value.get("provenance"), default_source="unknown"),
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
            belief_id=_text(value.get("belief_id"), limit=160),
            claim=_text(value.get("claim"), limit=2000),
            confidence=_bounded(value.get("confidence"), 0.5),
            basis=_text(value.get("basis"), limit=2000),
            status=_status(value.get("status"), BeliefStatus, BeliefStatus.HYPOTHESIS),
            first_formed_at=_number(value.get("first_formed_at", 0.0)),
            last_tested_at=_number(value.get("last_tested_at")) if value.get("last_tested_at") is not None else None,
            supporting_evidence_ids=_string_list(value.get("supporting_evidence_ids")),
            contradicting_evidence_ids=_string_list(value.get("contradicting_evidence_ids")),
            source_type=_text(value.get("source_type"), "inference", 64),
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
            episode_id=_text(value.get("episode_id"), limit=160),
            source_event_id=value.get("source_event_id"),
            simulation_timestamp=_number(value.get("simulation_timestamp", 0.0)),
            summary=_text(value.get("summary"), limit=2000),
            category=_text(value.get("category"), "general", 80),
            salience=_bounded(value.get("salience"), 0.5),
            status=_status(value.get("status"), EpisodeStatus, EpisodeStatus.RECENT),
            linked_task_ids=_string_list(value.get("linked_task_ids")),
            linked_note_ids=_string_list(value.get("linked_note_ids")),
            linked_belief_ids=_string_list(value.get("linked_belief_ids")),
            linked_marker_ids=_string_list(value.get("linked_marker_ids")),
            linked_memory_ids=_string_list(value.get("linked_memory_ids")),
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
    def from_dict(cls, value: Any) -> "AwakeningState":
        value = value if isinstance(value, dict) else {}
        return cls(
            narrative=_text(value.get("narrative"), AWAKENING_NARRATIVE, 4000),
            presented=bool(value.get("presented", False)),
            presented_at=_number(value.get("presented_at")) if value.get("presented_at") is not None else None,
        )


def starter_key_items() -> dict[str, KeyItem]:
    return {
        "blank_field_map": KeyItem(
            "blank_field_map", "Blank Field Map", "A blank field map for recording Ari's own knowledge.",
            Provenance("system_initialization", detail="v0.4.0 starter kit"),
        ),
        "task_journal": KeyItem(
            "task_journal", "Task Journal", "A journal containing broad survival reminders.",
            Provenance("system_initialization", detail="v0.4.0 starter kit"),
        ),
        "field_notebook": KeyItem(
            "field_notebook", "Field Notebook", "A notebook for Ari's own observations and notes.",
            Provenance("system_initialization", detail="v0.4.0 starter kit"),
        ),
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
                try:
                    record = BeliefRecord.from_dict({"belief_id": str(raw.get("belief_id") or key), **raw})
                except (KeyError, TypeError, ValueError):
                    continue
            elif isinstance(raw, (str, int, float, bool)):
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
            else:
                continue
            migrated[record.belief_id] = record
    elif isinstance(value, list):
        for raw in value:
            if isinstance(raw, dict) and raw.get("belief_id") and "claim" in raw:
                try:
                    record = BeliefRecord.from_dict(raw)
                except (KeyError, TypeError, ValueError):
                    continue
                migrated[record.belief_id] = record
    return migrated
