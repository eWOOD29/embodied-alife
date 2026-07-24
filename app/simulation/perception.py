from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

from app.simulation.actions import ari_record_origin_is_safe
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
    for raw_key in sorted(value, key=lambda item: str(item)):
        key = _truncate(raw_key, key_limit)
        if not key:
            continue
        raw_value = value[raw_key]
        if isinstance(raw_value, (int, float, bool)):
            projected: Any = _safe_number(raw_value) if not isinstance(raw_value, bool) else raw_value
        else:
            projected = _truncate(raw_value, value_limit)
        result[key] = projected
        if len(result) >= count_limit:
            break
    return result


def _known_tile_summaries(agent: AgentState, ax: int, ay: int) -> list[dict[str, Any]]:
    records: list[tuple[int, int, int, str]] = []
    known_terrain = agent.known_terrain if isinstance(agent.known_terrain, dict) else {}
    for raw_key, raw_terrain in known_terrain.items():
        if not isinstance(raw_key, str):
            continue
        try:
            x_text, y_text = raw_key.split(",", 1)
            world_x, world_y = int(x_text), int(y_text)
        except (AttributeError, TypeError, ValueError):
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
    for key, belief in beliefs.items():
        if not isinstance(belief, dict):
            continue
        status = str(belief.get("status", "hypothesis"))
        counts[status] = counts.get(status, 0) + 1
        timestamp = _safe_number(belief.get("last_tested_at") or belief.get("first_formed_at") or 0.0)
        records.append((timestamp, str(key), belief))
    records.sort(key=lambda item: (-item[0], item[1]))
    selected = [
        {
            "belief_id": _truncate(key, 96),
            "status": _truncate(belief.get("status", "hypothesis"), 32),
            "confidence": round(_safe_number(belief.get("confidence", 0.5), 0.5, minimum=0.0, maximum=1.0), 3),
            "claim": _truncate(belief.get("claim")),
            "basis": _truncate(belief.get("basis")),
        }
        for _, key, belief in records[:BELIEF_SUMMARY_LIMIT]
    ]
    return {"total": len(beliefs), "counts_by_status": dict(sorted(counts.items())), "selected": selected}


def _known_location_summaries(agent: AgentState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    known_locations = agent.known_locations if isinstance(agent.known_locations, dict) else {}
    for label, raw in sorted(known_locations.items(), key=lambda item: str(item[0])):
        if not isinstance(raw, dict):
            continue
        x, y = _safe_number(raw.get("x"), math.nan), _safe_number(raw.get("y"), math.nan)
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        dx, dy = x - _safe_number(agent.x), y - _safe_number(agent.y)
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
    maximum_coordinate = float(max(0, world.size - 1))
    agent_x = _safe_number(agent.x, 0.0, minimum=0.0, maximum=maximum_coordinate)
    agent_y = _safe_number(agent.y, 0.0, minimum=0.0, maximum=maximum_coordinate)
    ax, ay = int(round(agent_x)), int(round(agent_y))
    if not isinstance(agent.explored, set):
        agent.explored = set()
    if not isinstance(agent.known_terrain, dict):
        agent.known_terrain = {}
    if not isinstance(agent.known_locations, dict):
        agent.known_locations = {}
    visible_tiles: list[dict[str, Any]] = []
    terrain_counts: dict[str, int] = {}
    for y in range(max(0, ay - radius), min(world.size, ay + radius + 1)):
        for x in range(max(0, ax - radius), min(world.size, ax + radius + 1)):
            distance = math.hypot(x - ax, y - ay)
            if distance <= radius and has_line_of_sight(world, ax, ay, x, y):
                terrain = world.tile(x, y).value
                terrain_counts[terrain] = terrain_counts.get(terrain, 0) + 1
                visible_tiles.append({"offset_east": x - ax, "offset_south": y - ay, "terrain": terrain})
                key = f"{x},{y}"
                agent.explored.add(key)
                agent.known_terrain[key] = terrain
                if terrain == Terrain.CAVE.value:
                    agent.known_locations["cave_entrance"] = {"x": x, "y": y, "certainty": 1.0, "last_seen": world.sim_time}
                elif terrain == Terrain.BUILD_AREA.value:
                    agent.known_locations["stable_clearing"] = {"x": x, "y": y, "certainty": 0.9, "last_seen": world.sim_time}
                elif terrain in {Terrain.SHALLOW_WATER.value, Terrain.DEEP_WATER.value}:
                    water_key = f"water_near_{x // 8}_{y // 8}"
                    agent.known_locations[water_key] = {"x": x, "y": y, "certainty": 0.8, "last_seen": world.sim_time}

    objects: list[dict[str, Any]] = []
    resources = world.resources if isinstance(world.resources, dict) else {}
    for resource in resources.values():
        resource_x = _safe_number(getattr(resource, "x", None), math.nan)
        resource_y = _safe_number(getattr(resource, "y", None), math.nan)
        quantity = _safe_number(getattr(resource, "quantity", 0.0), 0.0)
        if not math.isfinite(resource_x) or not math.isfinite(resource_y) or quantity <= 0:
            continue
        rx, ry = int(round(resource_x)), int(round(resource_y))
        distance = math.hypot(resource_x - agent_x, resource_y - agent_y)
        if distance <= radius and has_line_of_sight(world, ax, ay, rx, ry):
            objects.append({
                "id": resource.id,
                "kind": resource.kind,
                "distance": round(distance, 1),
                "direction": _direction(resource_x - agent_x, resource_y - agent_y),
                "quantity": quantity,
                "portable": resource.portable,
                "appears_edible": resource.edible,
            })

    entities: list[dict[str, Any]] = []
    npcs = world.npcs if isinstance(world.npcs, dict) else {}
    for npc in npcs.values():
        npc_x = _safe_number(getattr(npc, "x", None), math.nan)
        npc_y = _safe_number(getattr(npc, "y", None), math.nan)
        if not math.isfinite(npc_x) or not math.isfinite(npc_y):
            continue
        distance = math.hypot(npc_x - agent_x, npc_y - agent_y)
        if distance <= radius and has_line_of_sight(world, ax, ay, int(round(npc_x)), int(round(npc_y))):
            classification = npc.kind if distance <= 4 else ("large animal" if npc.kind in {"deer", "wolf"} else "small moving creature")
            entities.append({
                "id": npc.id,
                "classification": classification,
                "distance": round(distance, 1),
                "direction": _direction(npc_x - agent_x, npc_y - agent_y),
                "behavior": npc.state,
                "danger_signs": npc.dangerous and distance <= 5,
            })

    shelter = world.nearby_shelter(agent_x, agent_y, 3.0)
    affordances = [
        "look", "move", "move_to", "inspect", "wait", "rest", "speak", "flee",
        "view_map", "view_task_journal", "view_notebook",
    ]
    if any(obj["distance"] <= INTERACTION_RADIUS and (obj["portable"] or obj["kind"] == "berry_bush") for obj in objects):
        affordances.append("pick_up")
    if any(obj["distance"] <= INTERACTION_RADIUS and obj["appears_edible"] for obj in objects) or any(
        key in agent.inventory for key in ("berry", "berry_bush", "edible_plant")
    ):
        affordances.append("eat")
    if any(
        world.is_water(x, y)
        for y in range(max(0, ay - 1), min(world.size, ay + 2))
        for x in range(max(0, ax - 1), min(world.size, ax + 2))
    ):
        affordances.append("drink")
    if agent.inventory:
        affordances.append("drop")
    if shelter or world.tile(ax, ay) in {Terrain.MEADOW, Terrain.BUILD_AREA, Terrain.CAVE}:
        affordances.append("sleep")
    if world.tile(ax, ay) == Terrain.BUILD_AREA:
        affordances.append("build")

    health_reserve = round(_safe_number(agent.health), 1)
    energy_reserve = round(_safe_number(agent.energy), 1)
    hunger_deficit = round(_safe_number(agent.hunger), 1)
    hydration_reserve = round(_safe_number(agent.hydration), 1)
    sleep_pressure = round(_safe_number(agent.sleep_pressure), 1)
    temperature_c = round(_safe_number(agent.body_temperature_c), 2)
    pain = round(_safe_number(agent.pain), 1)
    safe_needs = SimpleNamespace(
        health=health_reserve, energy=energy_reserve, hunger=hunger_deficit,
        hydration=hydration_reserve, sleep_pressure=sleep_pressure,
        body_temperature_c=temperature_c, pain=pain,
    )
    body = {
        "position": {"subjective_origin": "self"},
        "facing": _truncate(agent.facing, 32),
        "movement": "sleeping" if agent.sleeping else ("active" if agent.current_action else "stationary"),
        "health_reserve": health_reserve,
        "energy_reserve": energy_reserve,
        "hunger_deficit": hunger_deficit,
        "satiety": round(100.0 - hunger_deficit, 1),
        "hydration_reserve": hydration_reserve,
        "sleep_pressure": sleep_pressure,
        "temperature_c": temperature_c,
        "pain": pain,
        "inventory": _bounded_pairs(agent.inventory, count_limit=INVENTORY_SUMMARY_LIMIT, key_limit=80, value_limit=40),
        "inventory_capacity": int(_safe_number(agent.inventory_capacity, 0.0, minimum=0.0, maximum=10000.0)),
        "key_items": [_truncate(item.display_name, 120) for item in list(agent.key_items.values())[:KEY_ITEM_SUMMARY_LIMIT]],
        "scale_explanation": {
            "hunger_deficit": "0 is fully fed; 100 is starving",
            "satiety": "100 is fully fed; 0 is starving",
            "health_energy_hydration": "100 is best; 0 is critical",
            "sleep_pressure_and_pain": "0 is best; 100 is critical",
        },
        "health": round(_safe_number(agent.health), 1),
        "energy": round(_safe_number(agent.energy), 1),
        "hunger": hunger_deficit,
        "hydration": round(_safe_number(agent.hydration), 1),
    }
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
    cognition_summary = {
        "key_item_ids": [_truncate(item, KEY_ITEM_ID_LIMIT) for item in sorted((agent.key_items if isinstance(agent.key_items, dict) else {}), key=str)[:KEY_ITEM_SUMMARY_LIMIT]],
        "task_count": len(safe_tasks),
        "proposed_task_titles": [_truncate(getattr(task, "title", ""), TASK_TITLE_TEXT_LIMIT) for task in sorted(safe_tasks, key=lambda item: (_safe_number(getattr(item, "priority", 0)), _truncate(getattr(item, "task_id", ""), 96)))[:TASK_TITLE_SUMMARY_LIMIT]],
        "note_count": len(safe_notes),
        "map_marker_count": len(safe_markers),
        "belief_count": len(agent.beliefs) if isinstance(agent.beliefs, dict) else 0,
        "recent_episode_count": len(agent.short_term_episodes) if isinstance(agent.short_term_episodes, dict) else 0,
    }

    return {
        "awakening": agent.awakening.narrative if not agent.awakening.presented else None,
        "body": body,
        "cognitive_tools": cognition_summary,
        "drive_labels": drive_labels(safe_needs),
        "visible_objects": sorted(objects, key=lambda item: item["distance"])[:30],
        "visible_entities": sorted(entities, key=lambda item: item["distance"])[:12],
        "terrain_summary": terrain_counts,
        "local_tiles": visible_tiles,
        "underfoot": world.tile(ax, ay).value,
        "weather": world.weather,
        "ambient_temperature_c": world.ambient_temperature_c,
        "day": world.day,
        "hour": round(world.hour(), 1),
        "light": round(world.daylight(), 2),
        "near_shelter": ({"present": True, "quality": round(shelter.quality, 3)} if shelter else None),
        "available_actions": sorted(set(affordances)),
        "known_locations": _known_location_summaries(agent),
        "previously_explored": {
            "tile_count": len(agent.known_terrain) if isinstance(agent.known_terrain, dict) else 0,
            "nearby_known_tiles": _known_tile_summaries(agent, ax, ay),
        },
        "belief_summary": _belief_summary(agent),
        "personality_traits": _bounded_pairs(agent.personality_traits, count_limit=PERSONALITY_TRAIT_LIMIT, key_limit=PERSONALITY_KEY_LIMIT, value_limit=PERSONALITY_VALUE_LIMIT),
        "recent_events": [_safe_event_summary(event) for event in agent.recent_events[-10:]],
        "last_action_result": _safe_event_summary(agent.recent_events[-1]) if agent.recent_events else None,
    }
