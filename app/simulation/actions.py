from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.llm.schemas import ActionDecision
from app.serialization import finite_number, json_safe_dict
from app.simulation.agent import AgentState
from app.simulation.affordances import INTERACTION_RADIUS
from app.simulation.body import ActionExecution, astar, move_along_path
from app.simulation.integrity import verify_knowledge, verify_record
from app.simulation.world import Shelter, Terrain, WorldState


@dataclass(slots=True)
class ActionResult:
    success: bool
    action: str
    reason: str
    details: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_safe_dict(self, max_depth=8, max_items=256, max_text=4000)


DIRECTION_DELTAS = {
    "north": (0, -1), "northeast": (1, -1), "east": (1, 0), "southeast": (1, 1),
    "south": (0, 1), "southwest": (-1, 1), "west": (-1, 0), "northwest": (-1, -1),
}
VIEW_ACTIONS = {"view_map", "view_task_journal", "view_notebook"}


def _relative_direction(dx: float, dy: float) -> str:
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return "here"
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    labels = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
    return labels[int((angle + 22.5) // 45) % 8]


ARI_MARKER_TEXT_LIMIT = 160
ARI_MARKER_LINK_LIMIT = 8
ARI_LOCATION_TEXT_KEYS = {
    "direction": "direction",
    "relative_direction": "direction",
    "distance_band": "distance_band",
    "relative_distance": "distance_band",
    "description": "description",
}
ARI_PROVENANCE_CATEGORIES = {
    "agent": "agent",
    "ari": "agent",
    "inference": "inference",
    "perception": "perception",
    "observation": "perception",
    "system_initialization": "system",
    "task": "task",
    "note": "note",
}
ARI_DIRECT_SAFE_ORIGINS = {"agent", "ari", "inference", "perception", "observation"}
ARI_SYSTEM_TASK_CREATORS = {"starter_journal", "system_initialization"}
ARI_OBSERVER_OR_INTERNAL_ORIGINS = {
    "observer", "observer_only", "world_truth", "truth", "operational", "internal",
    "diagnostic", "database", "host", "extension", "unknown", "untrusted", "",
}
ARI_MAP_CELL_LIMIT = 64
ARI_MAP_MARKER_LIMIT = 32
ARI_TASK_LIMIT = 32
ARI_NOTE_LIMIT = 24
ARI_SOURCE_SCAN_LIMIT = 4096
ARI_TASK_TITLE_LIMIT = 160
ARI_TASK_DESCRIPTION_LIMIT = 480
ARI_NOTE_TITLE_LIMIT = 160
ARI_NOTE_CONTENT_LIMIT = 800
ARI_TAG_LIMIT = 12
ARI_TAG_TEXT_LIMIT = 64
RECENT_VIEW_MAP_CELL_LIMIT = 12
RECENT_VIEW_MARKER_LIMIT = 8
RECENT_VIEW_TASK_LIMIT = 8
RECENT_VIEW_NOTE_LIMIT = 6
RECENT_VIEW_TEXT_LIMIT = 360

_CREDENTIAL_PATTERN = re.compile(r"(?i)(?:bearer\s+|api[_-]?key\s*[:=]\s*|token\s*[:=]\s*)[A-Za-z0-9._~-]{12,}")
_WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:^|\s)[A-Z]:\\(?:[^\s\\]+\\)+[^\s\\]*")
_UNIX_HOME_PATTERN = re.compile(r"(?:^|\s)/(?:home|Users)/[^\s]+")
_DRIVE_URL_PATTERN = re.compile(r"https?://(?:docs|drive)\.google\.com/\S+", re.IGNORECASE)
_TAILNET_PATTERN = re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net\b", re.IGNORECASE)
_FORBIDDEN_LABEL_PATTERN = re.compile(r"(?i)\b(?:observer_?id|database_?id|internal_metadata|absolute_coordinates|private_path|operational_log)\s*[:=]")


def _bounded_text(value: Any, limit: int = ARI_MARKER_TEXT_LIMIT) -> str:
    if not isinstance(value, (str, int, float, bool)):
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _boundary_text(value: Any, limit: int) -> str:
    text = _bounded_text(value, limit)
    if not text:
        return ""
    if any(pattern.search(text) for pattern in (_CREDENTIAL_PATTERN, _WINDOWS_PATH_PATTERN, _UNIX_HOME_PATTERN, _DRIVE_URL_PATTERN, _TAILNET_PATTERN, _FORBIDDEN_LABEL_PATTERN)):
        return "[redacted]"
    return text


def _finite_number(value: Any, default: float | None = None) -> float | None:
    return finite_number(value, default)


def _origin(marker: Any) -> tuple[str, str]:
    provenance = getattr(marker, "provenance", None)
    if provenance is None:
        return "", ""
    if isinstance(provenance, dict):
        source_type = provenance.get("source_type")
        source_id = provenance.get("source_id")
    else:
        source_type = getattr(provenance, "source_type", None)
        source_id = getattr(provenance, "source_id", None)
    return _bounded_text(source_type, 64).lower(), _bounded_text(source_id, 160)


def ari_record_origin_is_safe(kind: str, record: Any, agent: AgentState, seen: set[tuple[str, str]] | None = None) -> bool:
    family = "marker" if kind in {"map_marker", "marker"} else kind
    return verify_record(family, record, agent)


def _safe_link_ids(values: Any, family: str, records: Any, agent: AgentState) -> list[str]:
    if not isinstance(records, dict) or not isinstance(values, (list, tuple, set)):
        return []
    if isinstance(values, set):
        if len(values) > ARI_MARKER_LINK_LIMIT * 4:
            return []
        scalar_values = [value for value in values if isinstance(value, (str, int)) and not isinstance(value, bool)]
        iterable = sorted(scalar_values, key=lambda value: (type(value).__name__, value))
    else:
        iterable = values
    selected: list[str] = []
    for raw in iterable:
        if not isinstance(raw, (str, int)) or isinstance(raw, bool):
            continue
        item = _bounded_text(raw, 96)
        linked = records.get(item)
        if item and linked is not None and verify_record(family, linked, agent) and item not in selected:
            selected.append(item)
        if len(selected) >= ARI_MARKER_LINK_LIMIT:
            break
    return selected


def _ari_location_projection(location: Any, agent: AgentState) -> dict[str, Any] | None:
    if not isinstance(location, dict):
        return None
    world_x = _finite_number(location.get("x"))
    world_y = _finite_number(location.get("y"))
    agent_x = _finite_number(getattr(agent, "x", None))
    agent_y = _finite_number(getattr(agent, "y", None))
    if world_x is not None and world_y is not None and agent_x is not None and agent_y is not None:
        dx, dy = world_x - agent_x, world_y - agent_y
        return {
            "direction": _relative_direction(dx, dy),
            "distance": round(min(10000.0, math.hypot(dx, dy)), 1),
            "offset_east": round(max(-10000.0, min(10000.0, dx)), 1),
            "offset_south": round(max(-10000.0, min(10000.0, dy)), 1),
        }
    projected: dict[str, Any] = {}
    for source_key, output_key in ARI_LOCATION_TEXT_KEYS.items():
        if source_key not in location or output_key in projected:
            continue
        text = _boundary_text(location.get(source_key), 120)
        if text:
            projected[output_key] = text
    if agent_x is not None and agent_y is not None:
        distance = _finite_number(location.get("distance"))
        if distance is not None and distance >= 0:
            projected["distance"] = round(min(distance, 10000.0), 1)
    uncertainty = _finite_number(location.get("uncertainty"))
    if uncertainty is not None:
        projected["uncertainty"] = round(max(0.0, min(1.0, uncertainty)), 3)
    confidence = _finite_number(location.get("confidence"))
    if confidence is not None:
        projected["confidence"] = round(max(0.0, min(1.0, confidence)), 3)
    return projected or None


def _ari_marker_projection(marker: Any, agent: AgentState) -> dict[str, Any] | None:
    if not ari_record_origin_is_safe("marker", marker, agent):
        return None
    source_type, _ = _origin(marker)
    item: dict[str, Any] = {
        "marker_id": _bounded_text(getattr(marker, "marker_id", ""), 96),
        "label": _boundary_text(getattr(marker, "label", "Unknown marker"), 120) or "Unknown marker",
        "marker_type": _boundary_text(getattr(marker, "marker_type", "unknown"), 64) or "unknown",
        "status": _safe_status(getattr(marker, "status", "active"), {"active", "stale", "archived"}, "active"),
        "confidence": round(max(0.0, min(1.0, _finite_number(getattr(marker, "confidence", 0.0), 0.0) or 0.0)), 3),
        "provenance_category": ARI_PROVENANCE_CATEGORIES[source_type],
    }
    location = _ari_location_projection(getattr(marker, "believed_location", None), agent)
    if location:
        item["believed_location"] = location
    tasks = agent.tasks if isinstance(agent.tasks, dict) else {}
    notes = agent.notes if isinstance(agent.notes, dict) else {}
    task_links = _safe_link_ids(getattr(marker, "linked_task_ids", []), "task", tasks, agent)
    note_links = _safe_link_ids(getattr(marker, "linked_note_ids", []), "note", notes, agent)
    if task_links:
        item["linked_task_ids"] = task_links
    if note_links:
        item["linked_note_ids"] = note_links
    return item


def _safe_status(value: Any, allowed: set[str], default: str) -> str:
    candidate = _bounded_text(value, 32).lower()
    return candidate if candidate in allowed else default


def _ari_priority(value: Any) -> int:
    number = _finite_number(value, 0.0)
    return int(max(-1000.0, min(1000.0, number or 0.0)))


def _ari_time(value: Any) -> float:
    number = _finite_number(value, 0.0)
    return round(max(0.0, min(1_000_000_000.0, number or 0.0)), 3)


def _ari_task_projection(task: Any, agent: AgentState) -> dict[str, Any] | None:
    if not ari_record_origin_is_safe("task", task, agent):
        return None
    source_type, _ = _origin(task)
    item = {
        "task_id": _bounded_text(getattr(task, "task_id", ""), 96),
        "title": _boundary_text(getattr(task, "title", "Untitled task"), ARI_TASK_TITLE_LIMIT) or "Untitled task",
        "description": _boundary_text(getattr(task, "description", ""), ARI_TASK_DESCRIPTION_LIMIT),
        "status": _safe_status(getattr(task, "status", "proposed"), {"proposed", "active", "suspended", "blocked", "completed", "abandoned", "superseded"}, "proposed"),
        "priority": _ari_priority(getattr(task, "priority", 0)),
        "created_at": _ari_time(getattr(task, "created_at", 0.0)),
        "updated_at": _ari_time(getattr(task, "updated_at", 0.0)),
        "provenance_category": ARI_PROVENANCE_CATEGORIES[source_type],
    }
    tasks = agent.tasks if isinstance(agent.tasks, dict) else {}
    markers = agent.map_markers if isinstance(agent.map_markers, dict) else {}
    notes = agent.notes if isinstance(agent.notes, dict) else {}
    parent = _bounded_text(getattr(task, "parent_task_id", ""), 96)
    parent_record = tasks.get(parent) if parent else None
    if parent_record is not None and verify_record("task", parent_record, agent):
        item["parent_task_id"] = parent
    marker_links = _safe_link_ids(getattr(task, "linked_marker_ids", []), "marker", markers, agent)
    note_links = _safe_link_ids(getattr(task, "linked_note_ids", []), "note", notes, agent)
    if marker_links:
        item["linked_marker_ids"] = marker_links
    if note_links:
        item["linked_note_ids"] = note_links
    return item


def _ari_note_projection(note: Any, agent: AgentState) -> dict[str, Any] | None:
    if not ari_record_origin_is_safe("note", note, agent):
        return None
    source_type, _ = _origin(note)
    item = {
        "note_id": _bounded_text(getattr(note, "note_id", ""), 96),
        "title": _boundary_text(getattr(note, "title", "Untitled note"), ARI_NOTE_TITLE_LIMIT) or "Untitled note",
        "content": _boundary_text(getattr(note, "content", ""), ARI_NOTE_CONTENT_LIMIT),
        "status": _safe_status(getattr(note, "status", "active"), {"active", "archived"}, "active"),
        "created_at": _ari_time(getattr(note, "created_at", 0.0)),
        "updated_at": _ari_time(getattr(note, "updated_at", 0.0)),
        "provenance_category": ARI_PROVENANCE_CATEGORIES[source_type],
    }
    tags = []
    raw_tags = getattr(note, "tags", [])
    if isinstance(raw_tags, (list, tuple, set)):
        if isinstance(raw_tags, set):
            scalar_tags = [value for value in raw_tags if isinstance(value, (str, int, float, bool))]
            iterable = sorted(scalar_tags, key=lambda value: (type(value).__name__, value))[:ARI_TAG_LIMIT]
        else:
            iterable = raw_tags
        for raw in iterable:
            tag = _boundary_text(raw, ARI_TAG_TEXT_LIMIT)
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= ARI_TAG_LIMIT:
                break
    if tags:
        item["tags"] = tags
    tasks = agent.tasks if isinstance(agent.tasks, dict) else {}
    markers = agent.map_markers if isinstance(agent.map_markers, dict) else {}
    task_links = _safe_link_ids(getattr(note, "linked_task_ids", []), "task", tasks, agent)
    marker_links = _safe_link_ids(getattr(note, "linked_marker_ids", []), "marker", markers, agent)
    if task_links:
        item["linked_task_ids"] = task_links
    if marker_links:
        item["linked_marker_ids"] = marker_links
    return item


def project_view_result_for_recent_outcome(action: str, data: Any) -> dict[str, Any] | None:
    """Create the one-decision, allowlisted handoff for a successful view action."""
    if action not in VIEW_ACTIONS or not isinstance(data, dict):
        return None
    if action == "view_map":
        cells: list[dict[str, Any]] = []
        for raw in data.get("known_cells", []) if isinstance(data.get("known_cells"), list) else []:
            if not isinstance(raw, dict):
                continue
            offset_east = _finite_number(raw.get("offset_east"))
            offset_south = _finite_number(raw.get("offset_south"))
            distance = _finite_number(raw.get("distance"))
            if offset_east is None or offset_south is None or distance is None or distance < 0:
                continue
            cell = {
                "offset_east": int(max(-10000, min(10000, offset_east))),
                "offset_south": int(max(-10000, min(10000, offset_south))),
                "distance": round(min(10000.0, distance), 1),
                "direction": _boundary_text(raw.get("direction"), 32),
                "terrain": _boundary_text(raw.get("terrain"), 64),
            }
            cells.append(cell)
            if len(cells) >= RECENT_VIEW_MAP_CELL_LIMIT:
                break
        markers: list[dict[str, Any]] = []
        allowed_marker = {"marker_id", "label", "marker_type", "status", "confidence", "provenance_category", "believed_location", "linked_task_ids", "linked_note_ids"}
        for raw in data.get("markers", []) if isinstance(data.get("markers"), list) else []:
            if not isinstance(raw, dict):
                continue
            projected = json_safe_dict({key: raw[key] for key in allowed_marker if key in raw}, max_depth=4, max_items=16, max_text=RECENT_VIEW_TEXT_LIMIT)
            if projected:
                markers.append(projected)
            if len(markers) >= RECENT_VIEW_MARKER_LIMIT:
                break
        return {
            "map_state": _boundary_text(data.get("map_state"), 32),
            "known_cells": cells,
            "markers": markers,
            "total_known_cells": int(max(0, min(1_000_000, _finite_number(data.get("total_known_cells"), 0.0) or 0.0))),
            "total_markers": int(max(0, min(1_000_000, _finite_number(data.get("total_markers"), 0.0) or 0.0))),
        }
    if action == "view_task_journal":
        allowed = {"task_id", "title", "description", "status", "priority", "created_at", "updated_at", "provenance_category", "parent_task_id", "linked_marker_ids", "linked_note_ids"}
        tasks: list[dict[str, Any]] = []
        for raw in data.get("tasks", []) if isinstance(data.get("tasks"), list) else []:
            if not isinstance(raw, dict):
                continue
            projected = json_safe_dict({key: raw[key] for key in allowed if key in raw}, max_depth=4, max_items=16, max_text=RECENT_VIEW_TEXT_LIMIT)
            if projected:
                tasks.append(projected)
            if len(tasks) >= RECENT_VIEW_TASK_LIMIT:
                break
        return {
            "tasks": tasks,
            "total_tasks": int(max(0, min(1_000_000, _finite_number(data.get("total_tasks"), 0.0) or 0.0))),
            "visible_tasks": len(tasks),
        }
    allowed = {"note_id", "title", "content", "status", "created_at", "updated_at", "provenance_category", "tags", "linked_task_ids", "linked_marker_ids"}
    notes: list[dict[str, Any]] = []
    for raw in data.get("notes", []) if isinstance(data.get("notes"), list) else []:
        if not isinstance(raw, dict):
            continue
        projected = json_safe_dict({key: raw[key] for key in allowed if key in raw}, max_depth=4, max_items=16, max_text=RECENT_VIEW_TEXT_LIMIT)
        if projected:
            notes.append(projected)
        if len(notes) >= RECENT_VIEW_NOTE_LIMIT:
            break
    return {
        "notes": notes,
        "empty": bool(data.get("empty", not notes)),
        "total_notes": int(max(0, min(1_000_000, _finite_number(data.get("total_notes"), 0.0) or 0.0))),
        "visible_notes": len(notes),
    }


class ActionController:
    def __init__(self) -> None:
        self.execution: ActionExecution | None = None

    def start(self, decision: ActionDecision, world: WorldState, agent: AgentState) -> ActionResult:
        if not agent.alive:
            return ActionResult(False, decision.action, "agent_dead", "The body cannot act.")
        if agent.sleeping:
            return ActionResult(False, decision.action, "already_sleeping", "The body is already asleep.")
        action = decision.action
        agent_x = _finite_number(getattr(agent, "x", None))
        agent_y = _finite_number(getattr(agent, "y", None))
        if action not in VIEW_ACTIONS | {"wait", "rest", "speak"} and (agent_x is None or agent_y is None):
            return ActionResult(False, action, "position_unknown", "The body's position is invalid; location-dependent action feasibility is unknown.")
        safe_agent_x = agent_x if agent_x is not None else 0.0
        safe_agent_y = agent_y if agent_y is not None else 0.0
        path: list[tuple[int, int]] = []
        metadata: dict[str, Any] = {"interrupt_if": list(decision.interrupt_if)}
        duration = decision.duration_seconds

        if action in {"move", "move_to", "flee"}:
            goal = self._resolve_goal(decision, world, agent)
            if goal is None:
                return ActionResult(False, action, "unknown_target", "No reachable target or direction was provided.")
            path = astar(world, (int(round(safe_agent_x)), int(round(safe_agent_y))), goal)
            if not path and goal != (int(round(safe_agent_x)), int(round(safe_agent_y))):
                return ActionResult(False, action, "target_unreachable", f"No legal path to {goal}.")
            duration = max(duration, max(0.5, len(path) / max(0.25, agent.movement_speed)))
            metadata["goal"] = list(goal)
        elif action == "pick_up":
            resource = world.resources.get(decision.target_id or "")
            if not resource or resource.quantity <= 0:
                return ActionResult(False, action, "target_missing", "The requested resource is not present.")
            if math.hypot(resource.x - safe_agent_x, resource.y - safe_agent_y) > INTERACTION_RADIUS:
                return ActionResult(False, action, "out_of_reach", "The resource is too far away.")
            if not resource.portable and resource.kind != "berry_bush":
                return ActionResult(False, action, "not_portable", "That object cannot be picked up.")
            if not agent.can_add(1):
                return ActionResult(False, action, "inventory_full", "The inventory is full.")
        elif action == "eat":
            if not self._find_edible(decision.target_id, world, agent):
                return ActionResult(False, action, "no_edible_item", "No edible item is available within reach or inventory.")
        elif action == "drink":
            if not self._near_water(world, agent):
                return ActionResult(False, action, "no_water", "No reachable water is close enough to drink.")
        elif action == "build":
            if world.tile(int(round(safe_agent_x)), int(round(safe_agent_y))) != Terrain.BUILD_AREA:
                return ActionResult(False, action, "illegal_location", "A basic shelter can only be built on stable clearing terrain.")
            if agent.inventory.get("branch", 0) < 3 or agent.inventory.get("stone", 0) < 2:
                return ActionResult(False, action, "missing_materials", "A shelter needs 3 branches and 2 stones.")
            if world.nearby_shelter(safe_agent_x, safe_agent_y, 2.0):
                return ActionResult(False, action, "already_built", "A shelter already occupies this location.")
            duration = max(12.0, duration)
        elif action == "drop":
            if decision.target_id in agent.key_items:
                return ActionResult(False, action, "key_item_protected", "Key items cannot be dropped.")
            if not decision.target_id or agent.inventory.get(decision.target_id, 0) <= 0:
                return ActionResult(False, action, "item_missing", "The requested inventory item is unavailable.")
        elif action == "inspect" and decision.target_id:
            if not self._target_near(decision.target_id, world, agent, INTERACTION_RADIUS):
                return ActionResult(False, action, "out_of_reach", "The target is not close enough to inspect.")
        elif action == "sleep":
            duration = max(15.0, duration)
            agent.sleeping = True
        elif action in VIEW_ACTIONS:
            duration = max(0.2, min(duration, 1.0))
        elif action not in {"look", "rest", "speak", "wait"}:
            return ActionResult(False, action, "unsupported_action", "The action is not supported by this controller.")

        if not agent.awakening.presented:
            agent.awakening.presented = True
            agent.awakening.presented_at = world.sim_time
        self.execution = ActionExecution(action, decision.target_id, duration, duration, path, decision.direction, world.sim_time, metadata)
        agent.current_action = self.execution.to_dict()
        agent.current_intention = decision.intent
        agent.last_decision_reason = decision.reason
        return ActionResult(True, action, "started", f"Action {action} began.", {"duration": duration})

    def step(self, dt: float, world: WorldState, agent: AgentState) -> tuple[bool, ActionResult | None, bool]:
        execution = self.execution
        if not execution:
            return False, None, False
        moving = execution.action in {"move", "move_to", "flee"} and bool(execution.path)
        if moving:
            move_along_path(agent, world, execution, dt)
        execution.remaining -= dt
        agent.current_action = execution.to_dict()
        completed = (execution.action in {"move", "move_to", "flee"} and not execution.path) or execution.remaining <= 0
        if not completed:
            return False, None, moving
        result = self._complete(execution, world, agent)
        self.execution = None
        agent.current_action = None
        return True, result, moving

    def interrupt(self, reason: str, agent: AgentState) -> ActionResult | None:
        if not self.execution:
            return None
        action = self.execution.action
        if action == "sleep":
            agent.sleeping = False
        self.execution = None
        agent.current_action = None
        return ActionResult(False, action, "interrupted", f"Action interrupted: {reason}.")

    def _complete(self, execution: ActionExecution, world: WorldState, agent: AgentState) -> ActionResult:
        action, target_id = execution.action, execution.target_id
        agent_x = _finite_number(getattr(agent, "x", None))
        agent_y = _finite_number(getattr(agent, "y", None))
        if action not in VIEW_ACTIONS | {"wait", "rest", "speak"} and (agent_x is None or agent_y is None):
            return ActionResult(False, action, "position_unknown", "The body's position became invalid; location-dependent completion is unknown.")
        safe_agent_x = agent_x if agent_x is not None else 0.0
        safe_agent_y = agent_y if agent_y is not None else 0.0
        if action in {"move", "move_to", "flee"}:
            return ActionResult(True, action, "completed", "The body reached the destination.", {"position": [round(safe_agent_x, 2), round(safe_agent_y, 2)]})
        if action == "pick_up":
            resources = world.resources if isinstance(getattr(world, "resources", None), dict) else {}
            resource = resources.get(target_id or "")
            quantity = _finite_number(getattr(resource, "quantity", None)) if resource is not None else None
            resource_x = _finite_number(getattr(resource, "x", None)) if resource is not None else None
            resource_y = _finite_number(getattr(resource, "y", None)) if resource is not None else None
            if resource is None or quantity is None or quantity <= 0 or resource_x is None or resource_y is None or math.hypot(resource_x - safe_agent_x, resource_y - safe_agent_y) > INTERACTION_RADIUS:
                return ActionResult(False, action, "target_changed", "The resource is no longer available within reach.")
            item_kind = "berry" if getattr(resource, "kind", "") == "berry_bush" else _bounded_text(getattr(resource, "kind", ""), 80)
            if not item_kind:
                return ActionResult(False, action, "target_changed", "The resource kind is no longer valid.")
            if not agent.add_item(item_kind, 1):
                return ActionResult(False, action, "inventory_full", "The inventory became full.")
            resource.quantity = quantity - 1
            resource.last_harvest_time = _finite_number(getattr(world, "sim_time", None), 0.0) or 0.0
            return ActionResult(True, action, "gathered", f"Picked up 1 {item_kind}.", {"item": item_kind})
        if action == "eat":
            edible = self._find_edible(target_id, world, agent)
            if not edible:
                return ActionResult(False, action, "edible_missing", "The edible item is no longer available.")
            source, kind = edible
            nutrition, energy = 12.0, 2.0
            if source == "inventory":
                agent.remove_item(kind, 1)
                if kind == "berry": nutrition, energy = 22.0, 5.0
            else:
                resource = world.resources[kind]
                resource.quantity -= 1
                resource.last_harvest_time = world.sim_time
                nutrition, energy, kind = resource.nutrition, resource.energy, resource.kind
            hunger = _finite_number(getattr(agent, "hunger", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            current_energy = _finite_number(getattr(agent, "energy", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            agent.hunger = max(0.0, hunger - nutrition)
            agent.energy = min(100.0, current_energy + energy)
            return ActionResult(True, action, "consumed", f"Ari ate {kind}.", {"nutrition": nutrition})
        if action == "drink":
            if not self._near_water(world, agent):
                return ActionResult(False, action, "water_unreachable", "Water is no longer within reach.")
            hydration = _finite_number(getattr(agent, "hydration", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            agent.hydration = min(100.0, hydration + 42.0)
            return ActionResult(True, action, "drank", "Ari drank from nearby water.", {"hydration_restored": 42.0})
        if action == "sleep":
            agent.sleeping = False
            return ActionResult(True, action, "woke", "Ari woke after real elapsed sleep time.")
        if action == "rest":
            current_energy = _finite_number(getattr(agent, "energy", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            agent.energy = min(100.0, current_energy + 5.0)
            return ActionResult(True, action, "rested", "Ari rested briefly.")
        if action == "build":
            if world.tile(int(round(safe_agent_x)), int(round(safe_agent_y))) != Terrain.BUILD_AREA:
                return ActionResult(False, action, "location_changed", "The build location is no longer legal.")
            inventory = agent.inventory if isinstance(getattr(agent, "inventory", None), dict) else {}
            branches = _finite_number(inventory.get("branch"), None, minimum=0.0, maximum=1_000_000.0)
            stones = _finite_number(inventory.get("stone"), None, minimum=0.0, maximum=1_000_000.0)
            if branches is None or stones is None or branches < 3 or stones < 2:
                return ActionResult(False, action, "materials_changed", "Required materials were no longer available.")
            agent.remove_item("branch", 3); agent.remove_item("stone", 2)
            shelters = world.shelters if isinstance(getattr(world, "shelters", None), dict) else {}
            shelter_id = f"shelter_{len(shelters) + 1:02d}"
            shelter = Shelter(shelter_id, int(round(safe_agent_x)), int(round(safe_agent_y)), quality=0.65)
            shelters[shelter_id] = shelter
            if isinstance(getattr(agent, "known_locations", None), dict):
                agent.known_locations[shelter_id] = {"x": shelter.x, "y": shelter.y, "certainty": 1.0, "last_seen": _finite_number(getattr(world, "sim_time", None), 0.0) or 0.0}
            return ActionResult(True, action, "built", "A basic shelter was built from branches and stones.", shelter.to_dict())
        if action == "drop":
            if target_id in agent.key_items:
                return ActionResult(False, action, "key_item_protected", "Key items cannot be dropped.")
            if not target_id or not agent.remove_item(target_id, 1):
                return ActionResult(False, action, "item_missing", "The item is no longer in inventory.")
            from app.simulation.world import Resource
            rid = f"dropped_{target_id}_{int(world.sim_time * 10)}"
            is_edible = target_id in {"berry", "edible_plant"}
            world.resources[rid] = Resource(rid, target_id, int(round(safe_agent_x)), int(round(safe_agent_y)), edible=is_edible,
                nutrition=22.0 if target_id == "berry" else (12.0 if is_edible else 0.0),
                energy=5.0 if target_id == "berry" else (2.0 if is_edible else 0.0))
            return ActionResult(True, action, "dropped", f"Dropped 1 {target_id}.")
        if action == "inspect":
            return ActionResult(True, action, "inspected", f"Inspected {target_id or 'the surroundings'}.")
        if action == "view_map":
            agent_x = _finite_number(getattr(agent, "x", None))
            agent_y = _finite_number(getattr(agent, "y", None))
            position_known = agent_x is not None and agent_y is not None
            ax = int(round(agent_x)) if position_known else 0
            ay = int(round(agent_y)) if position_known else 0
            cells: list[dict[str, Any]] = []
            total_cells = 0
            cell_scan_truncated = False
            known_terrain = agent.known_terrain if isinstance(agent.known_terrain, dict) else {}
            for index, (key, terrain) in enumerate(known_terrain.items()):
                if index >= ARI_SOURCE_SCAN_LIMIT:
                    cell_scan_truncated = True
                    break
                if not position_known or not isinstance(key, str) or not verify_knowledge(agent, "terrain", key, terrain):
                    continue
                try:
                    world_x, world_y = (int(part) for part in key.split(",", 1))
                    if not (-1_000_000 <= world_x <= 1_000_000 and -1_000_000 <= world_y <= 1_000_000):
                        continue
                except (AttributeError, TypeError, ValueError, OverflowError):
                    continue
                total_cells += 1
                dx, dy = world_x - ax, world_y - ay
                if len(cells) < ARI_MAP_CELL_LIMIT:
                    cells.append({
                        "offset_east": dx,
                        "offset_south": dy,
                        "distance": round(math.hypot(dx, dy), 1),
                        "direction": _relative_direction(dx, dy),
                        "terrain": _bounded_text(terrain, 64),
                    })
            cells.sort(key=lambda item: (item["distance"], item["offset_south"], item["offset_east"], item["terrain"]))
            cells = cells[:ARI_MAP_CELL_LIMIT]

            markers: list[dict[str, Any]] = []
            total_markers = 0
            marker_scan_truncated = False
            marker_values = agent.map_markers.values() if isinstance(agent.map_markers, dict) else []
            for index, marker in enumerate(marker_values):
                if index >= ARI_SOURCE_SCAN_LIMIT:
                    marker_scan_truncated = True
                    break
                if _safe_status(getattr(marker, "status", "active"), {"active", "stale", "archived"}, "active") == "archived":
                    continue
                projected = _ari_marker_projection(marker, agent)
                if projected is not None:
                    total_markers += 1
                    if len(markers) < ARI_MAP_MARKER_LIMIT:
                        markers.append(projected)
            markers.sort(key=lambda item: (item.get("status", ""), item.get("label", ""), item.get("marker_id", "")))
            return ActionResult(True, action, "viewed", "Ari reviewed the field map.", {
                "map_state": "blank" if not markers and not cells else "partially_known",
                "subjective_origin": "Ari's current position" if position_known else "unknown",
                "position_known": position_known,
                "known_cells": cells,
                "markers": markers,
                "total_known_cells": total_cells,
                "visible_known_cells": len(cells),
                "total_markers": total_markers,
                "visible_markers": len(markers),
                "source_scan_truncated": cell_scan_truncated or marker_scan_truncated,
            })
        if action == "view_task_journal":
            tasks: list[dict[str, Any]] = []
            total_tasks = 0
            status_counts: dict[str, int] = {}
            source_truncated = False
            task_values = agent.tasks.values() if isinstance(agent.tasks, dict) else []
            seen_ids: set[str] = set()
            for index, task in enumerate(task_values):
                if index >= ARI_SOURCE_SCAN_LIMIT:
                    source_truncated = True
                    break
                projected = _ari_task_projection(task, agent)
                if projected is None or projected["task_id"] in seen_ids:
                    continue
                seen_ids.add(projected["task_id"])
                total_tasks += 1
                status_counts[projected["status"]] = status_counts.get(projected["status"], 0) + 1
                tasks.append(projected)
            tasks.sort(key=lambda item: (item["priority"], item["created_at"], item["task_id"]))
            visible = tasks[:ARI_TASK_LIMIT]
            return ActionResult(True, action, "viewed", "Ari reviewed the task journal.", {
                "tasks": visible,
                "total_tasks": total_tasks,
                "visible_tasks": len(visible),
                "status_counts": dict(sorted(status_counts.items())),
                "source_scan_truncated": source_truncated,
            })
        if action == "view_notebook":
            notes: list[dict[str, Any]] = []
            total_notes = 0
            total_active = 0
            source_truncated = False
            note_values = agent.notes.values() if isinstance(agent.notes, dict) else []
            seen_ids: set[str] = set()
            for index, note in enumerate(note_values):
                if index >= ARI_SOURCE_SCAN_LIMIT:
                    source_truncated = True
                    break
                projected = _ari_note_projection(note, agent)
                if projected is None or projected["note_id"] in seen_ids:
                    continue
                seen_ids.add(projected["note_id"])
                total_notes += 1
                if projected["status"] == "active":
                    total_active += 1
                    notes.append(projected)
            notes.sort(key=lambda item: (-item["updated_at"], item["note_id"]))
            visible = notes[:ARI_NOTE_LIMIT]
            return ActionResult(True, action, "viewed", "The field notebook is empty." if not notes else "Ari reviewed the field notebook.", {
                "notes": visible,
                "empty": not notes,
                "total_notes": total_notes,
                "total_active_notes": total_active,
                "visible_notes": len(visible),
                "source_scan_truncated": source_truncated,
            })
        if action == "look":
            return ActionResult(True, action, "observed", "Ari deliberately surveyed the nearby area.")
        if action == "speak":
            return ActionResult(True, action, "spoken", "Ari spoke aloud; nearby entities may or may not respond.")
        return ActionResult(True, action, "completed", f"Action {action} completed.")

    def _resolve_goal(self, decision: ActionDecision, world: WorldState, agent: AgentState) -> tuple[int, int] | None:
        agent_x = _finite_number(agent.x, 0.0) or 0.0
        agent_y = _finite_number(agent.y, 0.0) or 0.0
        if decision.action == "flee":
            npcs = world.npcs if isinstance(world.npcs, dict) else {}
            dangers = [npc for npc in npcs.values() if bool(getattr(npc, "dangerous", False))]
            if not dangers:
                return None
            nearest = min(dangers, key=lambda npc: math.hypot((_finite_number(getattr(npc, "x", 0.0), 0.0) or 0.0) - agent_x, (_finite_number(getattr(npc, "y", 0.0), 0.0) or 0.0) - agent_y))
            nearest_x = _finite_number(getattr(nearest, "x", 0.0), 0.0) or 0.0
            nearest_y = _finite_number(getattr(nearest, "y", 0.0), 0.0) or 0.0
            dx, dy = agent_x - nearest_x, agent_y - nearest_y
            norm = max(0.001, math.hypot(dx, dy))
            for distance in (8, 6, 4, 2):
                goal = (int(round(agent_x + dx / norm * distance)), int(round(agent_y + dy / norm * distance)))
                if world.is_walkable(*goal):
                    return goal
        if decision.target_id:
            resources = world.resources if isinstance(world.resources, dict) else {}
            resource = resources.get(decision.target_id)
            if resource:
                return self._adjacent_walkable(world, int(_finite_number(getattr(resource, "x", 0.0), 0.0) or 0.0), int(_finite_number(getattr(resource, "y", 0.0), 0.0) or 0.0), agent)
            npcs = world.npcs if isinstance(world.npcs, dict) else {}
            npc = npcs.get(decision.target_id)
            if npc:
                return self._adjacent_walkable(world, int(_finite_number(getattr(npc, "x", 0.0), 0.0) or 0.0), int(_finite_number(getattr(npc, "y", 0.0), 0.0) or 0.0), agent)
            known_locations = agent.known_locations if isinstance(agent.known_locations, dict) else {}
            location = known_locations.get(decision.target_id)
            if isinstance(location, dict):
                x = _finite_number(location.get("x"))
                y = _finite_number(location.get("y"))
                if x is not None and y is not None:
                    return int(round(x)), int(round(y))
        if decision.direction in DIRECTION_DELTAS:
            dx, dy = DIRECTION_DELTAS[decision.direction]
            speed = max(0.25, _finite_number(agent.movement_speed, 2.0) or 2.0)
            duration = max(0.0, _finite_number(decision.duration_seconds, 1.0) or 1.0)
            distance = max(1, min(12, int(round(duration * speed))))
            for dist in range(distance, 0, -1):
                goal = (int(round(agent_x)) + dx * dist, int(round(agent_y)) + dy * dist)
                if world.is_walkable(*goal):
                    return goal
        return None

    @staticmethod
    def _adjacent_walkable(world: WorldState, x: int, y: int, agent: AgentState) -> tuple[int, int] | None:
        candidates = [(x, y)] + [(x + dx, y + dy) for dx, dy in DIRECTION_DELTAS.values()]
        valid = [point for point in candidates if world.is_walkable(*point)]
        agent_x = _finite_number(agent.x, 0.0) or 0.0
        agent_y = _finite_number(agent.y, 0.0) or 0.0
        return min(valid, key=lambda point: math.hypot(point[0] - agent_x, point[1] - agent_y)) if valid else None

    @staticmethod
    def _near_water(world: WorldState, agent: AgentState) -> bool:
        ax = int(round(_finite_number(agent.x, 0.0) or 0.0))
        ay = int(round(_finite_number(agent.y, 0.0) or 0.0))
        return any(world.is_water(x, y) for y in range(max(0, ay - 1), min(world.size, ay + 2)) for x in range(max(0, ax - 1), min(world.size, ax + 2)))

    @staticmethod
    def _find_edible(target_id: str | None, world: WorldState, agent: AgentState) -> tuple[str, str] | None:
        inventory = agent.inventory if isinstance(agent.inventory, dict) else {}
        if target_id and (_finite_number(inventory.get(target_id), 0.0) or 0.0) > 0 and target_id in {"berry", "edible_plant"}:
            return "inventory", target_id
        for kind in ("berry", "edible_plant"):
            if (_finite_number(inventory.get(kind), 0.0) or 0.0) > 0:
                return "inventory", kind
        resources = world.resources if isinstance(world.resources, dict) else {}
        agent_x = _finite_number(agent.x, 0.0) or 0.0
        agent_y = _finite_number(agent.y, 0.0) or 0.0
        candidates = [resources[target_id]] if target_id and target_id in resources else list(resources.values())
        for resource in candidates:
            resource_x = _finite_number(getattr(resource, "x", None))
            resource_y = _finite_number(getattr(resource, "y", None))
            quantity = _finite_number(getattr(resource, "quantity", 0.0), 0.0) or 0.0
            if resource_x is not None and resource_y is not None and bool(getattr(resource, "edible", False)) and quantity > 0 and math.hypot(resource_x - agent_x, resource_y - agent_y) <= INTERACTION_RADIUS:
                return "world", str(getattr(resource, "id", ""))
        return None

    @staticmethod
    def _target_near(target_id: str, world: WorldState, agent: AgentState, radius: float) -> bool:
        agent_x = _finite_number(agent.x, 0.0) or 0.0
        agent_y = _finite_number(agent.y, 0.0) or 0.0
        resources = world.resources if isinstance(world.resources, dict) else {}
        npcs = world.npcs if isinstance(world.npcs, dict) else {}
        locations = agent.known_locations if isinstance(agent.known_locations, dict) else {}
        target: Any = resources.get(target_id) or npcs.get(target_id)
        if target is not None:
            x = _finite_number(getattr(target, "x", None))
            y = _finite_number(getattr(target, "y", None))
        else:
            point = locations.get(target_id)
            x = _finite_number(point.get("x")) if isinstance(point, dict) else None
            y = _finite_number(point.get("y")) if isinstance(point, dict) else None
        return bool(x is not None and y is not None and math.hypot(x - agent_x, y - agent_y) <= radius)
