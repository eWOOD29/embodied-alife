from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.llm.schemas import ActionDecision
from app.simulation.agent import AgentState
from app.simulation.affordances import INTERACTION_RADIUS
from app.simulation.body import ActionExecution, astar, move_along_path
from app.simulation.world import Shelter, Terrain, WorldState


@dataclass(slots=True)
class ActionResult:
    success: bool
    action: str
    reason: str
    details: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    "memory": "memory",
    "task": "task",
    "note": "note",
    "system_initialization": "system",
}


def _bounded_text(value: Any, limit: int = ARI_MARKER_TEXT_LIMIT) -> str:
    if not isinstance(value, (str, int, float, bool)):
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _finite_number(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _safe_link_ids(values: Any, known_ids: set[str]) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    selected: list[str] = []
    iterable = sorted(values, key=lambda item: str(item)) if isinstance(values, set) else values
    for raw in iterable:
        if not isinstance(raw, (str, int)):
            continue
        item = _bounded_text(raw, 96)
        if item and item in known_ids and item not in selected:
            selected.append(item)
        if len(selected) >= ARI_MARKER_LINK_LIMIT:
            break
    return selected


def _ari_location_projection(location: Any, agent: AgentState) -> dict[str, Any] | None:
    if not isinstance(location, dict):
        return None
    world_x = _finite_number(location.get("x"))
    world_y = _finite_number(location.get("y"))
    if world_x is not None and world_y is not None:
        dx, dy = world_x - _finite_number(agent.x, 0.0), world_y - _finite_number(agent.y, 0.0)
        assert dx is not None and dy is not None
        return {
            "direction": _relative_direction(dx, dy),
            "distance": round(math.hypot(dx, dy), 1),
            "offset_east": round(dx, 1),
            "offset_south": round(dy, 1),
        }
    projected: dict[str, Any] = {}
    for source_key, output_key in ARI_LOCATION_TEXT_KEYS.items():
        if source_key not in location or output_key in projected:
            continue
        text = _bounded_text(location.get(source_key), 120)
        if text:
            projected[output_key] = text
    distance = _finite_number(location.get("distance"))
    if distance is not None:
        projected["distance"] = round(max(0.0, min(distance, 10000.0)), 1)
    uncertainty = _finite_number(location.get("uncertainty"))
    if uncertainty is not None:
        projected["uncertainty"] = round(max(0.0, min(1.0, uncertainty)), 3)
    confidence = _finite_number(location.get("confidence"))
    if confidence is not None:
        projected["confidence"] = round(max(0.0, min(1.0, confidence)), 3)
    return projected or None


def _ari_marker_projection(marker: Any, agent: AgentState) -> dict[str, Any]:
    source_type = _bounded_text(getattr(getattr(marker, "provenance", None), "source_type", ""), 48).lower()
    item: dict[str, Any] = {
        "marker_id": _bounded_text(getattr(marker, "marker_id", ""), 96),
        "label": _bounded_text(getattr(marker, "label", "Unknown marker"), 120),
        "marker_type": _bounded_text(getattr(marker, "marker_type", "unknown"), 64),
        "status": _bounded_text(getattr(marker, "status", "active"), 24),
        "confidence": round(max(0.0, min(1.0, _finite_number(getattr(marker, "confidence", 0.0), 0.0) or 0.0)), 3),
        "provenance_category": ARI_PROVENANCE_CATEGORIES.get(source_type, "subjective"),
    }
    location = _ari_location_projection(getattr(marker, "believed_location", None), agent)
    if location:
        item["believed_location"] = location
    task_links = _safe_link_ids(getattr(marker, "linked_task_ids", []), set(agent.tasks))
    note_links = _safe_link_ids(getattr(marker, "linked_note_ids", []), set(agent.notes))
    if task_links:
        item["linked_task_ids"] = task_links
    if note_links:
        item["linked_note_ids"] = note_links
    return item

ARI_MAP_CELL_LIMIT = 64
ARI_MAP_MARKER_LIMIT = 32
ARI_TASK_LIMIT = 32
ARI_NOTE_LIMIT = 24
ARI_TASK_TITLE_LIMIT = 160
ARI_TASK_DESCRIPTION_LIMIT = 480
ARI_NOTE_TITLE_LIMIT = 160
ARI_NOTE_CONTENT_LIMIT = 800
ARI_TAG_LIMIT = 12
ARI_TAG_TEXT_LIMIT = 64

ARI_FORBIDDEN_TEXT_FRAGMENTS = (
    "cave_truth", "recipe", "hidden_entity", "hidden_resource",
    "observer_id", "observerid", "database_id", "internal_metadata",
    "absolute_coordinates", "private_path", "hostname", "operational_log",
)


def _ari_boundary_text(value: Any, limit: int) -> str:
    text = _bounded_text(value, limit)
    lowered = text.lower().replace(" ", "_")
    return "" if any(fragment in lowered for fragment in ARI_FORBIDDEN_TEXT_FRAGMENTS) else text


def _safe_status(value: Any, allowed: set[str], default: str) -> str:
    candidate = _bounded_text(value, 32).lower()
    return candidate if candidate in allowed else default


def _ari_priority(value: Any) -> int:
    number = _finite_number(value, 0.0)
    return int(max(-1000.0, min(1000.0, number or 0.0)))


def _ari_time(value: Any) -> float:
    number = _finite_number(value, 0.0)
    return round(max(0.0, min(1_000_000_000.0, number or 0.0)), 3)


def _ari_task_projection(task: Any, agent: AgentState) -> dict[str, Any]:
    source_type = _bounded_text(getattr(getattr(task, "provenance", None), "source_type", ""), 48).lower()
    item = {
        "task_id": _bounded_text(getattr(task, "task_id", ""), 96),
        "title": _ari_boundary_text(getattr(task, "title", "Untitled task"), ARI_TASK_TITLE_LIMIT) or "Untitled task",
        "description": _ari_boundary_text(getattr(task, "description", ""), ARI_TASK_DESCRIPTION_LIMIT),
        "status": _safe_status(getattr(task, "status", "proposed"), {"proposed", "active", "suspended", "blocked", "completed", "abandoned", "superseded"}, "proposed"),
        "priority": _ari_priority(getattr(task, "priority", 0)),
        "created_at": _ari_time(getattr(task, "created_at", 0.0)),
        "updated_at": _ari_time(getattr(task, "updated_at", 0.0)),
        "provenance_category": ARI_PROVENANCE_CATEGORIES.get(source_type, "subjective"),
    }
    parent = _bounded_text(getattr(task, "parent_task_id", ""), 96)
    if parent and parent in agent.tasks:
        item["parent_task_id"] = parent
    marker_links = _safe_link_ids(getattr(task, "linked_marker_ids", []), set(agent.map_markers))
    note_links = _safe_link_ids(getattr(task, "linked_note_ids", []), set(agent.notes))
    if marker_links:
        item["linked_marker_ids"] = marker_links
    if note_links:
        item["linked_note_ids"] = note_links
    return item


def _ari_note_projection(note: Any, agent: AgentState) -> dict[str, Any]:
    source_type = _bounded_text(getattr(getattr(note, "provenance", None), "source_type", ""), 48).lower()
    item = {
        "note_id": _bounded_text(getattr(note, "note_id", ""), 96),
        "title": _ari_boundary_text(getattr(note, "title", "Untitled note"), ARI_NOTE_TITLE_LIMIT) or "Untitled note",
        "content": _ari_boundary_text(getattr(note, "content", ""), ARI_NOTE_CONTENT_LIMIT),
        "status": _safe_status(getattr(note, "status", "active"), {"active", "archived"}, "active"),
        "created_at": _ari_time(getattr(note, "created_at", 0.0)),
        "updated_at": _ari_time(getattr(note, "updated_at", 0.0)),
        "provenance_category": ARI_PROVENANCE_CATEGORIES.get(source_type, "subjective"),
    }
    tags = []
    raw_tags = getattr(note, "tags", [])
    if isinstance(raw_tags, (list, tuple, set)):
        iterable = sorted(raw_tags, key=lambda value: str(value)) if isinstance(raw_tags, set) else raw_tags
        for raw in iterable:
            tag = _ari_boundary_text(raw, ARI_TAG_TEXT_LIMIT)
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= ARI_TAG_LIMIT:
                break
    if tags:
        item["tags"] = tags
    task_links = _safe_link_ids(getattr(note, "linked_task_ids", []), set(agent.tasks))
    marker_links = _safe_link_ids(getattr(note, "linked_marker_ids", []), set(agent.map_markers))
    if task_links:
        item["linked_task_ids"] = task_links
    if marker_links:
        item["linked_marker_ids"] = marker_links
    return item


class ActionController:
    def __init__(self) -> None:
        self.execution: ActionExecution | None = None

    def start(self, decision: ActionDecision, world: WorldState, agent: AgentState) -> ActionResult:
        if not agent.alive:
            return ActionResult(False, decision.action, "agent_dead", "The body cannot act.")
        if agent.sleeping:
            return ActionResult(False, decision.action, "already_sleeping", "The body is already asleep.")
        action = decision.action
        path: list[tuple[int, int]] = []
        metadata: dict[str, Any] = {"interrupt_if": list(decision.interrupt_if)}
        duration = decision.duration_seconds

        if action in {"move", "move_to", "flee"}:
            goal = self._resolve_goal(decision, world, agent)
            if goal is None:
                return ActionResult(False, action, "unknown_target", "No reachable target or direction was provided.")
            path = astar(world, (int(round(agent.x)), int(round(agent.y))), goal)
            if not path and goal != (int(round(agent.x)), int(round(agent.y))):
                return ActionResult(False, action, "target_unreachable", f"No legal path to {goal}.")
            duration = max(duration, max(0.5, len(path) / max(0.25, agent.movement_speed)))
            metadata["goal"] = list(goal)
        elif action == "pick_up":
            resource = world.resources.get(decision.target_id or "")
            if not resource or resource.quantity <= 0:
                return ActionResult(False, action, "target_missing", "The requested resource is not present.")
            if math.hypot(resource.x - agent.x, resource.y - agent.y) > INTERACTION_RADIUS:
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
            if world.tile(int(round(agent.x)), int(round(agent.y))) != Terrain.BUILD_AREA:
                return ActionResult(False, action, "illegal_location", "A basic shelter can only be built on stable clearing terrain.")
            if agent.inventory.get("branch", 0) < 3 or agent.inventory.get("stone", 0) < 2:
                return ActionResult(False, action, "missing_materials", "A shelter needs 3 branches and 2 stones.")
            if world.nearby_shelter(agent.x, agent.y, 2.0):
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
        if action in {"move", "move_to", "flee"}:
            return ActionResult(True, action, "completed", "The body reached the destination.", {"position": [round(agent.x, 2), round(agent.y, 2)]})
        if action == "pick_up":
            resource = world.resources.get(target_id or "")
            if not resource or resource.quantity <= 0 or math.hypot(resource.x - agent.x, resource.y - agent.y) > INTERACTION_RADIUS:
                return ActionResult(False, action, "target_changed", "The resource is no longer available within reach.")
            item_kind = "berry" if resource.kind == "berry_bush" else resource.kind
            if not agent.add_item(item_kind, 1):
                return ActionResult(False, action, "inventory_full", "The inventory became full.")
            resource.quantity -= 1
            resource.last_harvest_time = world.sim_time
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
            agent.hunger = max(0.0, agent.hunger - nutrition)
            agent.energy = min(100.0, agent.energy + energy)
            return ActionResult(True, action, "consumed", f"Ari ate {kind}.", {"nutrition": nutrition})
        if action == "drink":
            if not self._near_water(world, agent):
                return ActionResult(False, action, "water_unreachable", "Water is no longer within reach.")
            agent.hydration = min(100.0, agent.hydration + 42.0)
            return ActionResult(True, action, "drank", "Ari drank from nearby water.", {"hydration_restored": 42.0})
        if action == "sleep":
            agent.sleeping = False
            return ActionResult(True, action, "woke", "Ari woke after real elapsed sleep time.")
        if action == "rest":
            agent.energy = min(100.0, agent.energy + 5.0)
            return ActionResult(True, action, "rested", "Ari rested briefly.")
        if action == "build":
            if world.tile(int(round(agent.x)), int(round(agent.y))) != Terrain.BUILD_AREA:
                return ActionResult(False, action, "location_changed", "The build location is no longer legal.")
            if agent.inventory.get("branch", 0) < 3 or agent.inventory.get("stone", 0) < 2:
                return ActionResult(False, action, "materials_changed", "Required materials were no longer available.")
            agent.remove_item("branch", 3); agent.remove_item("stone", 2)
            shelter_id = f"shelter_{len(world.shelters) + 1:02d}"
            shelter = Shelter(shelter_id, int(round(agent.x)), int(round(agent.y)), quality=0.65)
            world.shelters[shelter_id] = shelter
            agent.known_locations[shelter_id] = {"x": shelter.x, "y": shelter.y, "certainty": 1.0, "last_seen": world.sim_time}
            return ActionResult(True, action, "built", "A basic shelter was built from branches and stones.", shelter.to_dict())
        if action == "drop":
            if target_id in agent.key_items:
                return ActionResult(False, action, "key_item_protected", "Key items cannot be dropped.")
            if not target_id or not agent.remove_item(target_id, 1):
                return ActionResult(False, action, "item_missing", "The item is no longer in inventory.")
            from app.simulation.world import Resource
            rid = f"dropped_{target_id}_{int(world.sim_time * 10)}"
            is_edible = target_id in {"berry", "edible_plant"}
            world.resources[rid] = Resource(rid, target_id, int(round(agent.x)), int(round(agent.y)), edible=is_edible,
                nutrition=22.0 if target_id == "berry" else (12.0 if is_edible else 0.0),
                energy=5.0 if target_id == "berry" else (2.0 if is_edible else 0.0))
            return ActionResult(True, action, "dropped", f"Dropped 1 {target_id}.")
        if action == "inspect":
            return ActionResult(True, action, "inspected", f"Inspected {target_id or 'the surroundings'}.")
        if action == "view_map":
            agent_x = _finite_number(agent.x, 0.0) or 0.0
            agent_y = _finite_number(agent.y, 0.0) or 0.0
            ax, ay = int(round(agent_x)), int(round(agent_y))
            cells: list[dict[str, Any]] = []
            known_terrain = agent.known_terrain if isinstance(agent.known_terrain, dict) else {}
            for key, terrain in known_terrain.items():
                try:
                    world_x, world_y = (int(part) for part in key.split(",", 1))
                except (AttributeError, TypeError, ValueError, OverflowError):
                    continue
                dx, dy = world_x - ax, world_y - ay
                cells.append({
                    "offset_east": dx,
                    "offset_south": dy,
                    "distance": round(math.hypot(dx, dy), 1),
                    "direction": _relative_direction(dx, dy),
                    "terrain": _bounded_text(terrain, 64),
                })
            cells.sort(key=lambda item: (item["distance"], item["offset_south"], item["offset_east"], item["terrain"]))
            total_cells = len(cells)
            cells = cells[:ARI_MAP_CELL_LIMIT]
            markers: list[dict[str, Any]] = []
            marker_values = agent.map_markers.values() if isinstance(agent.map_markers, dict) else []
            for marker in marker_values:
                if _safe_status(getattr(marker, "status", "active"), {"active", "stale", "archived"}, "active") == "archived":
                    continue
                markers.append(_ari_marker_projection(marker, agent))
            markers.sort(key=lambda item: (item.get("status", ""), item.get("label", ""), item.get("marker_id", "")))
            total_markers = len(markers)
            markers = markers[:ARI_MAP_MARKER_LIMIT]
            return ActionResult(True, action, "viewed", "Ari reviewed the field map.", {
                "map_state": "blank" if not markers and not cells else "partially_known",
                "subjective_origin": "Ari's current position",
                "known_cells": cells,
                "markers": markers,
                "total_known_cells": total_cells,
                "visible_known_cells": len(cells),
                "total_markers": total_markers,
                "visible_markers": len(markers),
            })
        if action == "view_task_journal":
            task_values = list(agent.tasks.values()) if isinstance(agent.tasks, dict) else []
            tasks = [_ari_task_projection(task, agent) for task in task_values]
            tasks.sort(key=lambda item: (item["priority"], item["created_at"], item["task_id"]))
            status_counts: dict[str, int] = {}
            for item in tasks:
                status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
            visible = tasks[:ARI_TASK_LIMIT]
            return ActionResult(True, action, "viewed", "Ari reviewed the task journal.", {
                "tasks": visible,
                "total_tasks": len(tasks),
                "visible_tasks": len(visible),
                "status_counts": dict(sorted(status_counts.items())),
            })
        if action == "view_notebook":
            note_values = list(agent.notes.values()) if isinstance(agent.notes, dict) else []
            notes = [_ari_note_projection(note, agent) for note in note_values]
            active = [item for item in notes if item["status"] == "active"]
            active.sort(key=lambda item: (-item["updated_at"], item["note_id"]))
            visible = active[:ARI_NOTE_LIMIT]
            return ActionResult(True, action, "viewed", "The field notebook is empty." if not active else "Ari reviewed the field notebook.", {
                "notes": visible,
                "empty": not active,
                "total_notes": len(notes),
                "total_active_notes": len(active),
                "visible_notes": len(visible),
            })
        if action == "look":
            return ActionResult(True, action, "observed", "Ari deliberately surveyed the nearby area.")
        if action == "speak":
            return ActionResult(True, action, "spoken", "Ari spoke aloud; nearby entities may or may not respond.")
        return ActionResult(True, action, "completed", f"Action {action} completed.")

    def _resolve_goal(self, decision: ActionDecision, world: WorldState, agent: AgentState) -> tuple[int, int] | None:
        if decision.action == "flee":
            dangers = [npc for npc in world.npcs.values() if npc.dangerous]
            if not dangers: return None
            nearest = min(dangers, key=lambda npc: math.hypot(npc.x - agent.x, npc.y - agent.y))
            dx, dy = agent.x - nearest.x, agent.y - nearest.y
            norm = max(0.001, math.hypot(dx, dy))
            for distance in (8, 6, 4, 2):
                goal = (int(round(agent.x + dx / norm * distance)), int(round(agent.y + dy / norm * distance)))
                if world.is_walkable(*goal): return goal
        if decision.target_id:
            resource = world.resources.get(decision.target_id)
            if resource: return self._adjacent_walkable(world, resource.x, resource.y, agent)
            npc = world.npcs.get(decision.target_id)
            if npc: return self._adjacent_walkable(world, int(npc.x), int(npc.y), agent)
            location = agent.known_locations.get(decision.target_id)
            if location: return int(location["x"]), int(location["y"])
        if decision.direction:
            dx, dy = DIRECTION_DELTAS[decision.direction]
            distance = max(1, min(12, int(round(decision.duration_seconds * agent.movement_speed))))
            for dist in range(distance, 0, -1):
                goal = (int(round(agent.x)) + dx * dist, int(round(agent.y)) + dy * dist)
                if world.is_walkable(*goal): return goal
        return None

    @staticmethod
    def _adjacent_walkable(world: WorldState, x: int, y: int, agent: AgentState) -> tuple[int, int] | None:
        candidates = [(x, y)] + [(x + dx, y + dy) for dx, dy in DIRECTION_DELTAS.values()]
        valid = [point for point in candidates if world.is_walkable(*point)]
        return min(valid, key=lambda point: math.hypot(point[0] - agent.x, point[1] - agent.y)) if valid else None

    @staticmethod
    def _near_water(world: WorldState, agent: AgentState) -> bool:
        ax, ay = int(round(agent.x)), int(round(agent.y))
        return any(world.is_water(x, y) for y in range(max(0, ay - 1), min(world.size, ay + 2)) for x in range(max(0, ax - 1), min(world.size, ax + 2)))

    @staticmethod
    def _find_edible(target_id: str | None, world: WorldState, agent: AgentState) -> tuple[str, str] | None:
        if target_id and agent.inventory.get(target_id, 0) > 0 and target_id in {"berry", "edible_plant"}: return "inventory", target_id
        for kind in ("berry", "edible_plant"):
            if agent.inventory.get(kind, 0) > 0: return "inventory", kind
        if target_id and target_id in world.resources:
            resource = world.resources[target_id]
            if resource.edible and resource.quantity > 0 and math.hypot(resource.x - agent.x, resource.y - agent.y) <= INTERACTION_RADIUS: return "world", resource.id
        for resource in world.resources.values():
            if resource.edible and resource.quantity > 0 and math.hypot(resource.x - agent.x, resource.y - agent.y) <= INTERACTION_RADIUS: return "world", resource.id
        return None

    @staticmethod
    def _target_near(target_id: str, world: WorldState, agent: AgentState, radius: float) -> bool:
        if target_id in world.resources:
            resource = world.resources[target_id]; return math.hypot(resource.x - agent.x, resource.y - agent.y) <= radius
        if target_id in world.npcs:
            npc = world.npcs[target_id]; return math.hypot(npc.x - agent.x, npc.y - agent.y) <= radius
        if target_id in agent.known_locations:
            point = agent.known_locations[target_id]; return math.hypot(point["x"] - agent.x, point["y"] - agent.y) <= radius
        return False
