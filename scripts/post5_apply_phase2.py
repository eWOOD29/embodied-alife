from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_index] + replacement + text[end_index:]


# Ari view boundaries use content-bound verification and independently verify links.
actions = read("app/simulation/actions.py")
actions = replace_once(
    actions,
    "from app.simulation.body import ActionExecution, astar, move_along_path\n",
    '''from app.simulation.body import ActionExecution, astar, move_along_path
from app.simulation.integrity import verify_knowledge, verify_record
''',
    "actions integrity imports",
)
actions = replace_once(
    actions,
    "ARI_NOTE_LIMIT = 24\n",
    "ARI_NOTE_LIMIT = 24\nARI_SOURCE_SCAN_LIMIT = 4096\n",
    "actions source scan limit",
)
actions = replace_between(
    actions,
    "def ari_record_origin_is_safe(",
    "\n\ndef _safe_link_ids",
    '''def ari_record_origin_is_safe(kind: str, record: Any, agent: AgentState, seen: set[tuple[str, str]] | None = None) -> bool:
    family = "marker" if kind in {"map_marker", "marker"} else kind
    return verify_record(family, record, agent)
''',
    "actions origin policy",
)
actions = replace_between(
    actions,
    "def _safe_link_ids(",
    "\n\ndef _ari_location_projection",
    '''def _safe_link_ids(values: Any, family: str, records: Any, agent: AgentState) -> list[str]:
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
''',
    "actions linked authorization",
)
actions = replace_between(
    actions,
    "def _ari_location_projection(",
    "\n\ndef _ari_marker_projection",
    '''def _ari_location_projection(location: Any, agent: AgentState) -> dict[str, Any] | None:
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
''',
    "actions location projection",
)
actions = replace_once(actions, '_safe_link_ids(getattr(marker, "linked_task_ids", []), set(tasks))', '_safe_link_ids(getattr(marker, "linked_task_ids", []), "task", tasks, agent)', "marker task links")
actions = replace_once(actions, '_safe_link_ids(getattr(marker, "linked_note_ids", []), set(notes))', '_safe_link_ids(getattr(marker, "linked_note_ids", []), "note", notes, agent)', "marker note links")
actions = replace_once(actions, '_safe_link_ids(getattr(task, "linked_marker_ids", []), set(markers))', '_safe_link_ids(getattr(task, "linked_marker_ids", []), "marker", markers, agent)', "task marker links")
actions = replace_once(actions, '_safe_link_ids(getattr(task, "linked_note_ids", []), set(notes))', '_safe_link_ids(getattr(task, "linked_note_ids", []), "note", notes, agent)', "task note links")
actions = replace_once(actions, '_safe_link_ids(getattr(note, "linked_task_ids", []), set(tasks))', '_safe_link_ids(getattr(note, "linked_task_ids", []), "task", tasks, agent)', "note task links")
actions = replace_once(actions, '_safe_link_ids(getattr(note, "linked_marker_ids", []), set(markers))', '_safe_link_ids(getattr(note, "linked_marker_ids", []), "marker", markers, agent)', "note marker links")
actions = replace_once(
    actions,
    '''    parent = _bounded_text(getattr(task, "parent_task_id", ""), 96)
    if parent and parent in tasks:
        item["parent_task_id"] = parent
''',
    '''    parent = _bounded_text(getattr(task, "parent_task_id", ""), 96)
    parent_record = tasks.get(parent) if parent else None
    if parent_record is not None and verify_record("task", parent_record, agent):
        item["parent_task_id"] = parent
''',
    "task parent authorization",
)
actions = replace_once(
    actions,
    '''    if isinstance(raw_tags, (list, tuple, set)):
        iterable = sorted(raw_tags, key=lambda value: str(value)) if isinstance(raw_tags, set) else raw_tags
        for raw in iterable:
''',
    '''    if isinstance(raw_tags, (list, tuple, set)):
        if isinstance(raw_tags, set):
            scalar_tags = [value for value in raw_tags if isinstance(value, (str, int, float, bool))]
            iterable = sorted(scalar_tags, key=lambda value: (type(value).__name__, value))[:ARI_TAG_LIMIT]
        else:
            iterable = raw_tags
        for raw in iterable:
''',
    "note tags bounded",
)
# Do not invent zero-valued coordinates in the immediate-to-recent projection.
actions = replace_once(
    actions,
    '''            cell = {
                "offset_east": int(max(-10000, min(10000, _finite_number(raw.get("offset_east"), 0.0) or 0.0))),
                "offset_south": int(max(-10000, min(10000, _finite_number(raw.get("offset_south"), 0.0) or 0.0))),
                "distance": round(max(0.0, min(10000.0, _finite_number(raw.get("distance"), 0.0) or 0.0)), 1),
                "direction": _boundary_text(raw.get("direction"), 32),
                "terrain": _boundary_text(raw.get("terrain"), 64),
            }
            cells.append(cell)
''',
    '''            offset_east = _finite_number(raw.get("offset_east"))
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
''',
    "recent map coordinate projection",
)
# View action production paths: bounded scans, proof checks, unknown-position semantics.
view_block = '''        if action == "view_map":
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
'''
actions = replace_between(actions, '        if action == "view_map":\n', '        if action == "look":\n', view_block, "actions view branches")
# Position-dependent controller actions fail closed instead of using (0, 0).
actions = replace_once(
    actions,
    '''        action = decision.action
        agent_x = _finite_number(agent.x, 0.0) or 0.0
        agent_y = _finite_number(agent.y, 0.0) or 0.0
        path: list[tuple[int, int]] = []
''',
    '''        action = decision.action
        agent_x = _finite_number(getattr(agent, "x", None))
        agent_y = _finite_number(getattr(agent, "y", None))
        if action not in VIEW_ACTIONS | {"wait", "rest", "speak"} and (agent_x is None or agent_y is None):
            return ActionResult(False, action, "position_unknown", "The body's position is invalid; location-dependent action feasibility is unknown.")
        safe_agent_x = agent_x if agent_x is not None else 0.0
        safe_agent_y = agent_y if agent_y is not None else 0.0
        path: list[tuple[int, int]] = []
''',
    "actions start position",
)
actions = actions.replace("int(round(agent_x)), int(round(agent_y))", "int(round(safe_agent_x)), int(round(safe_agent_y))")
actions = actions.replace("resource.x - agent_x, resource.y - agent_y", "resource.x - safe_agent_x, resource.y - safe_agent_y")
actions = actions.replace("world.nearby_shelter(agent_x, agent_y, 2.0)", "world.nearby_shelter(safe_agent_x, safe_agent_y, 2.0)")
write("app/simulation/actions.py", actions)


# Perception preserves malformed source state and emits unknown instead of clamped location claims.
perception = read("app/simulation/perception.py")
perception = replace_once(
    perception,
    "from app.simulation.actions import ari_record_origin_is_safe\n",
    '''from app.simulation.actions import ari_record_origin_is_safe
from app.simulation.integrity import seal_knowledge, verify_knowledge, verify_record
''',
    "perception integrity imports",
)
perception = replace_between(
    perception,
    "def _bounded_pairs(",
    "\n\ndef _safe_event_summary",
    '''def _bounded_pairs(value: Any, *, count_limit: int, key_limit: int, value_limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for index, (raw_key, raw_value) in enumerate(value.items()):
        if index >= count_limit:
            break
        key = _truncate(raw_key, key_limit)
        if not key:
            continue
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            projected: Any = _safe_number(raw_value)
        elif isinstance(raw_value, bool):
            projected = raw_value
        else:
            projected = _truncate(raw_value, value_limit)
        result[key] = projected
    return result


def _known_tile_summaries(agent: AgentState, ax: int | None, ay: int | None) -> list[dict[str, Any]]:
    if ax is None or ay is None:
        return []
    records: list[tuple[int, int, int, str]] = []
    known_terrain = agent.known_terrain if isinstance(agent.known_terrain, dict) else {}
    for index, (raw_key, raw_terrain) in enumerate(known_terrain.items()):
        if index >= 4096 or not isinstance(raw_key, str) or not verify_knowledge(agent, "terrain", raw_key, raw_terrain):
            continue
        try:
            x_text, y_text = raw_key.split(",", 1)
            world_x, world_y = int(x_text), int(y_text)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        records.append((abs(world_x - ax) + abs(world_y - ay), world_x, world_y, _truncate(raw_terrain, 64)))
    records.sort(key=lambda item: (item[0], item[2], item[1], item[3]))
    return [
        {"offset_east": world_x - ax, "offset_south": world_y - ay, "terrain": terrain}
        for _, world_x, world_y, terrain in records[:KNOWN_TILE_SUMMARY_LIMIT]
    ]


def _belief_summary(agent: AgentState) -> dict[str, Any]:
    counts: dict[str, int] = {}
    records: list[tuple[float, str, Any]] = []
    beliefs = agent.beliefs if isinstance(agent.beliefs, dict) else {}
    verified_total = 0
    for index, (key, belief) in enumerate(beliefs.items()):
        if index >= 4096 or not isinstance(belief, dict) or not verify_record("belief", belief, agent):
            continue
        verified_total += 1
        status = _truncate(belief.get("status", "hypothesis"), 32) or "hypothesis"
        counts[status] = counts.get(status, 0) + 1
        timestamp = _safe_number(belief.get("last_tested_at") or belief.get("first_formed_at") or 0.0)
        records.append((timestamp, _truncate(key, 96), belief))
    records.sort(key=lambda item: (-item[0], item[1]))
    selected = [
        {
            "belief_id": key,
            "status": _truncate(belief.get("status", "hypothesis"), 32),
            "confidence": round(_safe_number(belief.get("confidence", 0.5), 0.5, minimum=0.0, maximum=1.0), 3),
            "claim": _truncate(belief.get("claim")),
            "basis": _truncate(belief.get("basis")),
        }
        for _, key, belief in records[:BELIEF_SUMMARY_LIMIT]
    ]
    return {"total": verified_total, "counts_by_status": dict(sorted(counts.items())), "selected": selected}


def _known_location_summaries(agent: AgentState, agent_x: float | None, agent_y: float | None) -> list[dict[str, Any]]:
    if agent_x is None or agent_y is None:
        return []
    result: list[dict[str, Any]] = []
    known_locations = agent.known_locations if isinstance(agent.known_locations, dict) else {}
    for index, (label, raw) in enumerate(known_locations.items()):
        if index >= 4096 or not isinstance(raw, dict):
            continue
        identity = _truncate(label, 160)
        if not identity or not verify_knowledge(agent, "location", identity, raw):
            continue
        x, y = _safe_number(raw.get("x"), math.nan), _safe_number(raw.get("y"), math.nan)
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        dx, dy = x - agent_x, y - agent_y
        result.append({
            "label": _truncate(label, 80),
            "direction": _direction(dx, dy),
            "distance": round(math.hypot(dx, dy), 1),
            "certainty": round(_safe_number(raw.get("certainty", 0.0), 0.0, minimum=0.0, maximum=1.0), 3),
        })
    result.sort(key=lambda item: (item["distance"], item["label"]))
    return result[:KNOWN_LOCATION_SUMMARY_LIMIT]
''',
    "perception helpers",
)
new_build = '''def build_perception(world: WorldState, agent: AgentState, radius: int = 10) -> dict[str, Any]:
    world_size_number = _safe_number(getattr(world, "size", None), math.nan)
    world_size = int(world_size_number) if math.isfinite(world_size_number) and world_size_number >= 1 else 0
    raw_x = _safe_number(getattr(agent, "x", None), math.nan)
    raw_y = _safe_number(getattr(agent, "y", None), math.nan)
    position_known = (
        world_size > 0
        and math.isfinite(raw_x)
        and math.isfinite(raw_y)
        and 0.0 <= raw_x <= world_size - 1
        and 0.0 <= raw_y <= world_size - 1
    )
    agent_x = raw_x if position_known else None
    agent_y = raw_y if position_known else None
    ax = int(round(agent_x)) if agent_x is not None else None
    ay = int(round(agent_y)) if agent_y is not None else None

    explored_store = agent.explored if isinstance(agent.explored, set) else None
    terrain_store = agent.known_terrain if isinstance(agent.known_terrain, dict) else None
    location_store = agent.known_locations if isinstance(agent.known_locations, dict) else None

    visible_tiles: list[dict[str, Any]] = []
    terrain_counts: dict[str, int] = {}
    if ax is not None and ay is not None:
        for y in range(max(0, ay - radius), min(world_size, ay + radius + 1)):
            for x in range(max(0, ax - radius), min(world_size, ax + radius + 1)):
                distance = math.hypot(x - ax, y - ay)
                if distance > radius or not has_line_of_sight(world, ax, ay, x, y):
                    continue
                terrain = world.tile(x, y).value
                terrain_counts[terrain] = terrain_counts.get(terrain, 0) + 1
                visible_tiles.append({"offset_east": x - ax, "offset_south": y - ay, "terrain": terrain})
                key = f"{x},{y}"
                if explored_store is not None:
                    explored_store.add(key)
                if terrain_store is not None:
                    terrain_store[key] = terrain
                    seal_knowledge(agent, "terrain", key, terrain, "validated_perception", source_ref=f"perception:{getattr(world, 'sim_time', 0)}:{key}")
                location_key = None
                certainty = None
                if terrain == Terrain.CAVE.value:
                    location_key, certainty = "cave_entrance", 1.0
                elif terrain == Terrain.BUILD_AREA.value:
                    location_key, certainty = "stable_clearing", 0.9
                elif terrain in {Terrain.SHALLOW_WATER.value, Terrain.DEEP_WATER.value}:
                    location_key, certainty = f"water_near_{x // 8}_{y // 8}", 0.8
                if location_store is not None and location_key is not None:
                    value = {"x": x, "y": y, "certainty": certainty, "last_seen": _safe_number(getattr(world, "sim_time", 0.0))}
                    location_store[location_key] = value
                    seal_knowledge(agent, "location", location_key, value, "validated_perception", source_ref=f"perception:{getattr(world, 'sim_time', 0)}:{location_key}")

    objects: list[dict[str, Any]] = []
    resources = world.resources if isinstance(getattr(world, "resources", None), dict) else {}
    if agent_x is not None and agent_y is not None and ax is not None and ay is not None:
        for index, resource in enumerate(resources.values()):
            if index >= 4096:
                break
            resource_x = _safe_number(getattr(resource, "x", None), math.nan)
            resource_y = _safe_number(getattr(resource, "y", None), math.nan)
            quantity = _safe_number(getattr(resource, "quantity", None), math.nan)
            resource_id = _truncate(getattr(resource, "id", ""), 160)
            kind = _truncate(getattr(resource, "kind", ""), 80)
            if not resource_id or not kind or not math.isfinite(resource_x) or not math.isfinite(resource_y) or not math.isfinite(quantity) or quantity <= 0:
                continue
            rx, ry = int(round(resource_x)), int(round(resource_y))
            distance = math.hypot(resource_x - agent_x, resource_y - agent_y)
            if distance <= radius and has_line_of_sight(world, ax, ay, rx, ry):
                objects.append({
                    "id": resource_id,
                    "kind": kind,
                    "distance": round(distance, 1),
                    "direction": _direction(resource_x - agent_x, resource_y - agent_y),
                    "quantity": quantity,
                    "portable": getattr(resource, "portable", None) is True,
                    "appears_edible": getattr(resource, "edible", None) is True,
                })

    entities: list[dict[str, Any]] = []
    npcs = world.npcs if isinstance(getattr(world, "npcs", None), dict) else {}
    if agent_x is not None and agent_y is not None and ax is not None and ay is not None:
        for index, npc in enumerate(npcs.values()):
            if index >= 4096:
                break
            npc_x = _safe_number(getattr(npc, "x", None), math.nan)
            npc_y = _safe_number(getattr(npc, "y", None), math.nan)
            npc_id = _truncate(getattr(npc, "id", ""), 160)
            kind = _truncate(getattr(npc, "kind", ""), 80)
            if not npc_id or not math.isfinite(npc_x) or not math.isfinite(npc_y):
                continue
            distance = math.hypot(npc_x - agent_x, npc_y - agent_y)
            if distance <= radius and has_line_of_sight(world, ax, ay, int(round(npc_x)), int(round(npc_y))):
                classification = kind if distance <= 4 else ("large animal" if kind in {"deer", "wolf"} else "small moving creature")
                entities.append({
                    "id": npc_id,
                    "classification": classification,
                    "distance": round(distance, 1),
                    "direction": _direction(npc_x - agent_x, npc_y - agent_y),
                    "behavior": _truncate(getattr(npc, "state", ""), 80),
                    "danger_signs": getattr(npc, "dangerous", None) is True and distance <= 5,
                })

    shelter = None
    underfoot = None
    if agent_x is not None and agent_y is not None and ax is not None and ay is not None:
        try:
            shelter = world.nearby_shelter(agent_x, agent_y, 3.0)
        except Exception:
            shelter = None
        try:
            underfoot = world.tile(ax, ay)
        except Exception:
            underfoot = None

    affordances = ["view_map", "view_task_journal", "view_notebook", "wait", "rest", "speak"]
    if position_known:
        affordances.extend(["look", "move", "move_to", "inspect", "flee"])
        if any(obj["distance"] <= INTERACTION_RADIUS and (obj["portable"] or obj["kind"] == "berry_bush") for obj in objects):
            affordances.append("pick_up")
        inventory = agent.inventory if isinstance(agent.inventory, dict) else {}
        if any(obj["distance"] <= INTERACTION_RADIUS and obj["appears_edible"] for obj in objects) or any(
            isinstance(inventory.get(key), int) and not isinstance(inventory.get(key), bool) and inventory.get(key, 0) > 0
            for key in ("berry", "berry_bush", "edible_plant")
        ):
            affordances.append("eat")
        if any(
            world.is_water(x, y)
            for y in range(max(0, ay - 1), min(world_size, ay + 2))
            for x in range(max(0, ax - 1), min(world_size, ax + 2))
        ):
            affordances.append("drink")
        if any(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in inventory.values()):
            affordances.append("drop")
        if shelter or underfoot in {Terrain.MEADOW, Terrain.BUILD_AREA, Terrain.CAVE}:
            affordances.append("sleep")
        if underfoot == Terrain.BUILD_AREA and inventory.get("branch", 0) >= 3 and inventory.get("stone", 0) >= 2:
            affordances.append("build")

    health_reserve = round(_safe_number(getattr(agent, "health", None)), 1)
    energy_reserve = round(_safe_number(getattr(agent, "energy", None)), 1)
    hunger_deficit = round(_safe_number(getattr(agent, "hunger", None)), 1)
    hydration_reserve = round(_safe_number(getattr(agent, "hydration", None)), 1)
    sleep_pressure = round(_safe_number(getattr(agent, "sleep_pressure", None)), 1)
    temperature_c = round(_safe_number(getattr(agent, "body_temperature_c", None)), 2)
    pain = round(_safe_number(getattr(agent, "pain", None)), 1)
    safe_needs = SimpleNamespace(
        health=health_reserve, energy=energy_reserve, hunger=hunger_deficit,
        hydration=hydration_reserve, sleep_pressure=sleep_pressure,
        body_temperature_c=temperature_c, pain=pain,
    )

    key_items = [
        item for item in (agent.key_items.values() if isinstance(agent.key_items, dict) else [])
        if verify_record("key_item", item, agent)
    ]
    safe_tasks = [
        task for task in (agent.tasks.values() if isinstance(agent.tasks, dict) else [])
        if ari_record_origin_is_safe("task", task, agent)
    ]
    safe_notes = [
        note for note in (agent.notes.values() if isinstance(agent.notes, dict) else [])
        if ari_record_origin_is_safe("note", note, agent)
    ]
    safe_markers = [
        marker for marker in (agent.map_markers.values() if isinstance(agent.map_markers, dict) else [])
        if ari_record_origin_is_safe("marker", marker, agent)
    ]
    safe_episodes = [
        episode for episode in (agent.short_term_episodes.values() if isinstance(agent.short_term_episodes, dict) else [])
        if verify_record("episode", episode, agent)
    ]

    body = {
        "position": {"subjective_origin": "self", "known": position_known},
        "facing": _truncate(getattr(agent, "facing", ""), 32),
        "movement": "sleeping" if getattr(agent, "sleeping", False) is True else ("active" if isinstance(getattr(agent, "current_action", None), dict) else "stationary"),
        "health_reserve": health_reserve,
        "energy_reserve": energy_reserve,
        "hunger_deficit": hunger_deficit,
        "satiety": round(100.0 - hunger_deficit, 1),
        "hydration_reserve": hydration_reserve,
        "sleep_pressure": sleep_pressure,
        "temperature_c": temperature_c,
        "pain": pain,
        "inventory": _bounded_pairs(getattr(agent, "inventory", None), count_limit=INVENTORY_SUMMARY_LIMIT, key_limit=80, value_limit=40),
        "inventory_capacity": int(_safe_number(getattr(agent, "inventory_capacity", None), 0.0, minimum=0.0, maximum=10000.0)),
        "key_items": [_truncate(getattr(item, "display_name", ""), 120) for item in key_items[:KEY_ITEM_SUMMARY_LIMIT]],
        "scale_explanation": {
            "hunger_deficit": "0 is fully fed; 100 is starving",
            "satiety": "100 is fully fed; 0 is starving",
            "health_energy_hydration": "100 is best; 0 is critical",
            "sleep_pressure_and_pain": "0 is best; 100 is critical",
        },
        "health": health_reserve,
        "energy": energy_reserve,
        "hunger": hunger_deficit,
        "hydration": hydration_reserve,
    }
    cognition_summary = {
        "key_item_ids": [_truncate(getattr(item, "key_item_id", ""), KEY_ITEM_ID_LIMIT) for item in key_items[:KEY_ITEM_SUMMARY_LIMIT]],
        "task_count": len(safe_tasks),
        "proposed_task_titles": [_truncate(getattr(task, "title", ""), TASK_TITLE_TEXT_LIMIT) for task in sorted(safe_tasks, key=lambda item: (_safe_number(getattr(item, "priority", 0)), _truncate(getattr(item, "task_id", ""), 96)))[:TASK_TITLE_SUMMARY_LIMIT]],
        "note_count": len(safe_notes),
        "map_marker_count": len(safe_markers),
        "belief_count": _belief_summary(agent)["total"],
        "recent_episode_count": len(safe_episodes),
    }

    recent_events = agent.recent_events if isinstance(agent.recent_events, list) else []
    try:
        hour = round(_safe_number(world.hour()), 1)
    except Exception:
        hour = None
    try:
        light = round(_safe_number(world.daylight()), 2)
    except Exception:
        light = None
    return {
        "awakening": agent.awakening.narrative if isinstance(agent.awakening, object) and not getattr(agent.awakening, "presented", False) else None,
        "body": body,
        "cognitive_tools": cognition_summary,
        "drive_labels": drive_labels(safe_needs),
        "visible_objects": sorted(objects, key=lambda item: item["distance"])[:30],
        "visible_entities": sorted(entities, key=lambda item: item["distance"])[:12],
        "terrain_summary": terrain_counts,
        "local_tiles": visible_tiles,
        "underfoot": underfoot.value if isinstance(underfoot, Terrain) else "unknown",
        "weather": _truncate(getattr(world, "weather", ""), 80),
        "ambient_temperature_c": _safe_number(getattr(world, "ambient_temperature_c", None), 0.0),
        "day": int(_safe_number(getattr(world, "day", None), 0.0)),
        "hour": hour,
        "light": light,
        "near_shelter": ({"present": True, "quality": round(_safe_number(getattr(shelter, "quality", None), 0.0, minimum=0.0, maximum=1.0), 3)} if shelter else None),
        "available_actions": sorted(set(affordances)),
        "known_locations": _known_location_summaries(agent, agent_x, agent_y),
        "previously_explored": {
            "tile_count": sum(1 for key, value in (terrain_store.items() if terrain_store is not None else []) if verify_knowledge(agent, "terrain", key, value)),
            "nearby_known_tiles": _known_tile_summaries(agent, ax, ay),
        },
        "belief_summary": _belief_summary(agent),
        "personality_traits": _bounded_pairs(getattr(agent, "personality_traits", None), count_limit=PERSONALITY_TRAIT_LIMIT, key_limit=PERSONALITY_KEY_LIMIT, value_limit=PERSONALITY_VALUE_LIMIT),
        "recent_events": [_safe_event_summary(event) for event in recent_events[-10:]],
        "last_action_result": _safe_event_summary(recent_events[-1]) if recent_events else None,
    }
'''
perception = replace_between(perception, "def build_perception(", "", new_build, "perception build") if False else perception[:perception.find("def build_perception(")] + new_build
write("app/simulation/perception.py", perception)

print("post5 phase2 applied")
