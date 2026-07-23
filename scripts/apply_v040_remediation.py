from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected text not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# R1: Ari-facing map and ordinary perception must never expose absolute coordinates.
replace(
    "app/simulation/actions.py",
    '''        if action == "view_map":
            markers = [marker.to_dict() for marker in agent.map_markers.values() if marker.status != "archived"]
            known = {key: value for key, value in agent.known_terrain.items()}
            return ActionResult(True, action, "viewed", "Ari reviewed the field map.", {
                "map_state": "blank" if not markers and not known else "partially_known",
                "known_terrain": known,
                "markers": markers,
                "observer_truth_included": False,
            })
''',
    '''        if action == "view_map":
            ax, ay = int(round(agent.x)), int(round(agent.y))
            cells: list[dict[str, Any]] = []
            for key, terrain in agent.known_terrain.items():
                try:
                    world_x, world_y = (int(part) for part in key.split(",", 1))
                except (AttributeError, TypeError, ValueError):
                    continue
                dx, dy = world_x - ax, world_y - ay
                cells.append({
                    "offset_east": dx,
                    "offset_south": dy,
                    "distance": round(math.hypot(dx, dy), 1),
                    "direction": _relative_direction(dx, dy),
                    "terrain": str(terrain),
                })
            cells.sort(key=lambda item: (item["distance"], item["offset_south"], item["offset_east"]))
            markers: list[dict[str, Any]] = []
            for marker in agent.map_markers.values():
                if marker.status == "archived":
                    continue
                item = marker.to_dict()
                location = item.pop("believed_location", None)
                if isinstance(location, dict) and isinstance(location.get("x"), (int, float)) and isinstance(location.get("y"), (int, float)):
                    dx, dy = float(location["x"]) - agent.x, float(location["y"]) - agent.y
                    item["believed_location"] = {
                        "direction": _relative_direction(dx, dy),
                        "distance": round(math.hypot(dx, dy), 1),
                        "offset_east": round(dx, 1),
                        "offset_south": round(dy, 1),
                    }
                elif location is not None:
                    item["believed_location"] = _strip_coordinate_fields(location)
                markers.append(_strip_coordinate_fields(item))
            return ActionResult(True, action, "viewed", "Ari reviewed the field map.", {
                "map_state": "blank" if not markers and not cells else "partially_known",
                "subjective_origin": "Ari's current position",
                "known_cells": cells,
                "markers": markers,
            })
''',
)
replace(
    "app/simulation/actions.py",
    'VIEW_ACTIONS = {"view_map", "view_task_journal", "view_notebook"}\n',
    '''VIEW_ACTIONS = {"view_map", "view_task_journal", "view_notebook"}


def _relative_direction(dx: float, dy: float) -> str:
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return "here"
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    labels = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
    return labels[int((angle + 22.5) // 45) % 8]


def _strip_coordinate_fields(value: Any) -> Any:
    forbidden = {"x", "y", "world_x", "world_y", "coordinates", "absolute_coordinates", "observer_id"}
    if isinstance(value, dict):
        return {key: _strip_coordinate_fields(item) for key, item in value.items() if str(key).lower() not in forbidden}
    if isinstance(value, list):
        return [_strip_coordinate_fields(item) for item in value]
    return value
''',
)

replace(
    "app/simulation/perception.py",
    'INTERACTION_RADIUS = 2.2\n',
    '''INTERACTION_RADIUS = 2.2
BELIEF_SUMMARY_LIMIT = 6
BELIEF_TEXT_LIMIT = 160
KNOWN_TILE_SUMMARY_LIMIT = 64
KNOWN_LOCATION_SUMMARY_LIMIT = 12


def _truncate(value: Any, limit: int = BELIEF_TEXT_LIMIT) -> str:
    text = str(value or "").replace("\\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _belief_summary(agent: AgentState) -> dict[str, Any]:
    counts: dict[str, int] = {}
    records: list[tuple[float, str, Any]] = []
    for key, belief in agent.beliefs.items():
        status = str(belief.get("status", "hypothesis"))
        counts[status] = counts.get(status, 0) + 1
        timestamp = float(belief.get("last_tested_at") or belief.get("first_formed_at") or 0.0)
        records.append((timestamp, str(key), belief))
    records.sort(key=lambda item: (-item[0], item[1]))
    selected = [
        {
            "belief_id": key,
            "status": str(belief.get("status", "hypothesis")),
            "confidence": round(float(belief.get("confidence", 0.5)), 3),
            "claim": _truncate(belief.get("claim")),
            "basis": _truncate(belief.get("basis")),
        }
        for _, key, belief in records[:BELIEF_SUMMARY_LIMIT]
    ]
    return {"total": len(agent.beliefs), "counts_by_status": dict(sorted(counts.items())), "selected": selected}


def _known_location_summaries(agent: AgentState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for label, raw in sorted(agent.known_locations.items()):
        if not isinstance(raw, dict):
            continue
        x, y = raw.get("x"), raw.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        dx, dy = float(x) - agent.x, float(y) - agent.y
        result.append({
            "label": _truncate(label, 80),
            "direction": _direction(dx, dy),
            "distance": round(math.hypot(dx, dy), 1),
            "certainty": round(max(0.0, min(1.0, float(raw.get("certainty", 0.0)))), 3),
        })
    result.sort(key=lambda item: (item["distance"], item["label"]))
    return result[:KNOWN_LOCATION_SUMMARY_LIMIT]


def _safe_event_summary(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {"message": _truncate(event, 200)}
    return {
        "sim_time": event.get("sim_time"),
        "kind": _truncate(event.get("kind"), 60),
        "message": _truncate(event.get("message"), 240),
        "importance": event.get("importance"),
    }
''',
)
replace(
    "app/simulation/perception.py",
    '        "position": {"x": round(agent.x, 1), "y": round(agent.y, 1)},\n',
    '        "position": {"subjective_origin": "self"},\n',
)
replace(
    "app/simulation/perception.py",
    '        "near_shelter": shelter.to_dict() if shelter else None,\n',
    '        "near_shelter": ({"present": True, "quality": round(shelter.quality, 3)} if shelter else None),\n',
)
replace(
    "app/simulation/perception.py",
    '        "known_locations": agent.known_locations,\n',
    '        "known_locations": _known_location_summaries(agent),\n',
)
replace(
    "app/simulation/perception.py",
    '                )[:250]\n',
    '                )[:KNOWN_TILE_SUMMARY_LIMIT]\n',
)
replace(
    "app/simulation/perception.py",
    '        "beliefs": {key: belief.to_dict() for key, belief in agent.beliefs.items()},\n',
    '        "belief_summary": _belief_summary(agent),\n',
)
replace(
    "app/simulation/perception.py",
    '        "recent_events": agent.recent_events[-10:],\n        "last_action_result": agent.recent_events[-1] if agent.recent_events else None,\n',
    '        "recent_events": [_safe_event_summary(event) for event in agent.recent_events[-10:]],\n        "last_action_result": _safe_event_summary(agent.recent_events[-1]) if agent.recent_events else None,\n',
)

# R3: restore exact snapshot experiment state; audit load outside the payload.
replace(
    "app/simulation/scheduler.py",
    '''        self._restore(state)
        self.paused = True
        self._record("snapshot", f"Snapshot '{name}' loaded; simulation paused.", 0.5, {"name": name})
        self._persist_current()
        return {"ok": True, "name": name, "sim_time": self.world.sim_time}
''',
    '''        self._restore(state)
        self.database.set_metadata("last_snapshot_load_audit", {
            "name": name,
            "sim_time": self.world.sim_time,
            "run_id": self.run_id,
            "world_generation_id": self.world_generation_id,
        })
        self._persist_current()
        return {"ok": True, "name": name, "sim_time": self.world.sim_time}
''',
)

# R4/R5: distinguish absent from empty and guard malformed stores.
replace(
    "app/simulation/agent.py",
    '''        raw_key_items = copied.get("key_items")
        copied["key_items"] = (
            {key: KeyItem.from_dict({"key_item_id": key, **value}) for key, value in raw_key_items.items()}
            if isinstance(raw_key_items, dict) and raw_key_items
            else starter_key_items()
        )
        raw_tasks = copied.get("tasks")
        copied["tasks"] = (
            {key: TaskRecord.from_dict({"task_id": key, **value}) for key, value in raw_tasks.items()}
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
        copied["beliefs"] = BeliefStore(copied.get("beliefs"))
        copied["short_term_episodes"] = {
            key: EpisodeRecord.from_dict({"episode_id": key, **value})
            for key, value in (copied.get("short_term_episodes") or {}).items()
        }
''',
    '''        raw_key_items = copied.get("key_items") if "key_items" in copied else None
        copied["key_items"] = starter_key_items() if "key_items" not in copied else _load_records(raw_key_items, KeyItem, "key_item_id")
        raw_tasks = copied.get("tasks") if "tasks" in copied else None
        copied["tasks"] = starter_tasks() if "tasks" not in copied else _load_records(raw_tasks, TaskRecord, "task_id")
        copied["notes"] = _load_records(copied.get("notes"), NoteRecord, "note_id")
        copied["map_markers"] = _load_records(copied.get("map_markers"), MapMarker, "marker_id")
        copied["beliefs"] = BeliefStore(copied.get("beliefs"))
        copied["short_term_episodes"] = _load_records(copied.get("short_term_episodes"), EpisodeRecord, "episode_id")
''',
)
replace(
    "app/simulation/agent.py",
    '@dataclass(slots=True)\nclass AgentState:',
    '''def _load_records(value: Any, record_type: Any, id_field: str) -> dict[str, Any]:
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
class AgentState:''',
)

# Schema normalization is conservative: malformed optional records are quarantined by omission.
replace(
    "app/simulation/cognition.py",
    'COGNITION_SCHEMA_VERSION = 1\n',
    '''COGNITION_SCHEMA_VERSION = 1


def _bounded(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _status(value: Any, enum_type: type[StrEnum], default: StrEnum) -> str:
    candidate = str(value or default.value)
    allowed = {item.value for item in enum_type}
    return candidate if candidate in allowed else default.value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) else []
''',
)
for old, new in [
    ('status=str(value.get("status", TaskStatus.PROPOSED.value)),', 'status=_status(value.get("status"), TaskStatus, TaskStatus.PROPOSED),'),
    ('metadata=dict(value.get("metadata") or {}),', 'metadata=_dict(value.get("metadata")),'),
    ('linked_marker_ids=list(value.get("linked_marker_ids") or []),', 'linked_marker_ids=[str(item) for item in _list(value.get("linked_marker_ids"))],'),
    ('linked_note_ids=list(value.get("linked_note_ids") or []),', 'linked_note_ids=[str(item) for item in _list(value.get("linked_note_ids"))],'),
    ('tags=list(value.get("tags") or []),', 'tags=[str(item) for item in _list(value.get("tags"))],'),
    ('status=str(value.get("status", NoteStatus.ACTIVE.value)),', 'status=_status(value.get("status"), NoteStatus, NoteStatus.ACTIVE),'),
    ('linked_task_ids=list(value.get("linked_task_ids") or []),', 'linked_task_ids=[str(item) for item in _list(value.get("linked_task_ids"))],'),
    ('believed_location=dict(value["believed_location"]) if value.get("believed_location") is not None else None,', 'believed_location=_dict(value.get("believed_location")) or None,'),
    ('confidence=float(value.get("confidence", 0.0)),', 'confidence=_bounded(value.get("confidence"), 0.0),'),
    ('status=str(value.get("status", MarkerStatus.ACTIVE.value)),', 'status=_status(value.get("status"), MarkerStatus, MarkerStatus.ACTIVE),'),
    ('confidence=float(value.get("confidence", 0.5)),', 'confidence=_bounded(value.get("confidence"), 0.5),'),
    ('status=str(value.get("status", BeliefStatus.HYPOTHESIS.value)),', 'status=_status(value.get("status"), BeliefStatus, BeliefStatus.HYPOTHESIS),'),
    ('supporting_evidence_ids=list(value.get("supporting_evidence_ids") or []),', 'supporting_evidence_ids=[str(item) for item in _list(value.get("supporting_evidence_ids"))],'),
    ('contradicting_evidence_ids=list(value.get("contradicting_evidence_ids") or []),', 'contradicting_evidence_ids=[str(item) for item in _list(value.get("contradicting_evidence_ids"))],'),
    ('salience=float(value.get("salience", 0.5)),', 'salience=_bounded(value.get("salience"), 0.5),'),
    ('status=str(value.get("status", EpisodeStatus.RECENT.value)),', 'status=_status(value.get("status"), EpisodeStatus, EpisodeStatus.RECENT),'),
    ('linked_belief_ids=list(value.get("linked_belief_ids") or []),', 'linked_belief_ids=[str(item) for item in _list(value.get("linked_belief_ids"))],'),
    ('linked_memory_ids=list(value.get("linked_memory_ids") or []),', 'linked_memory_ids=[str(item) for item in _list(value.get("linked_memory_ids"))],'),
]:
    replace("app/simulation/cognition.py", old, new)

# Mixed malformed beliefs: retain valid subjective beliefs, omit malformed records without promoting truth.
replace(
    "app/simulation/cognition.py",
    '''            if isinstance(raw, dict) and "claim" in raw:
                record = BeliefRecord.from_dict({"belief_id": str(raw.get("belief_id") or key), **raw})
            else:
                record = BeliefRecord(
''',
    '''            if isinstance(raw, dict) and "claim" in raw:
                try:
                    record = BeliefRecord.from_dict({"belief_id": str(raw.get("belief_id") or key), **raw})
                except (KeyError, TypeError, ValueError):
                    continue
            elif isinstance(raw, (str, int, float, bool)):
                record = BeliefRecord(
''',
)
replace(
    "app/simulation/cognition.py",
    '''                    provenance=Provenance("legacy_migration", source_id=str(key)),
                )
            migrated[record.belief_id] = record
''',
    '''                    provenance=Provenance("legacy_migration", source_id=str(key)),
                )
            else:
                continue
            migrated[record.belief_id] = record
''',
)
replace(
    "app/simulation/cognition.py",
    '''            if isinstance(raw, dict):
                record = BeliefRecord.from_dict(raw)
                migrated[record.belief_id] = record
''',
    '''            if isinstance(raw, dict) and raw.get("belief_id") and "claim" in raw:
                try:
                    record = BeliefRecord.from_dict(raw)
                except (KeyError, TypeError, ValueError):
                    continue
                migrated[record.belief_id] = record
''',
)

print("Applied v0.4.0 remediation source changes")
