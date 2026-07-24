from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

from app.simulation.actions import ari_record_origin_is_safe
from app.simulation.integrity import seal_knowledge, verify_knowledge, verify_record
from app.simulation.agent import AgentState
from app.simulation.needs import drive_labels
from app.simulation.world import BLOCKING_TERRAIN, Terrain, WorldState

INTERACTION_RADIUS = 2.2
BELIEF_SUMMARY_LIMIT = 6
BELIEF_TEXT_LIMIT = 160
KNOWN_TILE_SUMMARY_LIMIT = 64
KNOWN_LOCATION_SUMMARY_LIMIT = 12
KEY_ITEM_SUMMARY_LIMIT = 8
KEY_ITEM_ID_LIMIT = 96
TASK_TITLE_SUMMARY_LIMIT = 4
TASK_TITLE_TEXT_LIMIT = 160
PERSONALITY_TRAIT_LIMIT = 12
PERSONALITY_KEY_LIMIT = 64
PERSONALITY_VALUE_LIMIT = 120
INVENTORY_SUMMARY_LIMIT = 24
ACTIVE_TEXT_LIMIT = 240


def _truncate(value: Any, limit: int = BELIEF_TEXT_LIMIT) -> str:
    if not isinstance(value, (str, int, float, bool)):
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:
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


def _bounded_pairs(value: Any, *, count_limit: int, key_limit: int, value_limit: int) -> dict[str, Any]:
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


def _safe_event_summary(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {"message": _truncate(event, 200)}
    return {
        "sim_time": _safe_number(event.get("sim_time"), 0.0),
        "kind": _truncate(event.get("kind"), 60),
        "message": _truncate(event.get("message"), 240),
        "importance": round(_safe_number(event.get("importance"), 0.0, minimum=0.0, maximum=1.0), 3),
    }


def _line_points(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return points


def has_line_of_sight(world: WorldState, x0: int, y0: int, x1: int, y1: int) -> bool:
    return all(world.tile(x, y) not in BLOCKING_TERRAIN for x, y in _line_points(x0, y0, x1, y1)[1:-1])


def _direction(dx: float, dy: float) -> str:
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    labels = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
    return labels[int((angle + 22.5) // 45) % 8]


def build_perception(world: WorldState, agent: AgentState, radius: int = 10) -> dict[str, Any]:
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
