from __future__ import annotations

import math
from typing import Any

from app.simulation.agent import AgentState
from app.simulation.needs import drive_labels
from app.simulation.world import BLOCKING_TERRAIN, Terrain, WorldState

INTERACTION_RADIUS = 2.2
BELIEF_SUMMARY_LIMIT = 6
BELIEF_TEXT_LIMIT = 160
KNOWN_TILE_SUMMARY_LIMIT = 64
KNOWN_LOCATION_SUMMARY_LIMIT = 12


def _truncate(value: Any, limit: int = BELIEF_TEXT_LIMIT) -> str:
    text = str(value or "").replace("\n", " ").strip()
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
    ax, ay = int(round(agent.x)), int(round(agent.y))
    visible_tiles: list[dict[str, Any]] = []
    terrain_counts: dict[str, int] = {}
    for y in range(max(0, ay - radius), min(world.size, ay + radius + 1)):
        for x in range(max(0, ax - radius), min(world.size, ax + radius + 1)):
            distance = math.hypot(x - ax, y - ay)
            if distance <= radius and has_line_of_sight(world, ax, ay, x, y):
                terrain = world.tile(x, y).value
                terrain_counts[terrain] = terrain_counts.get(terrain, 0) + 1
                visible_tiles.append({"x": x - ax, "y": y - ay, "terrain": terrain})
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
    for resource in world.resources.values():
        if resource.quantity <= 0:
            continue
        distance = math.hypot(resource.x - agent.x, resource.y - agent.y)
        if distance <= radius and has_line_of_sight(world, ax, ay, resource.x, resource.y):
            objects.append({
                "id": resource.id,
                "kind": resource.kind,
                "distance": round(distance, 1),
                "direction": _direction(resource.x - agent.x, resource.y - agent.y),
                "quantity": resource.quantity,
                "portable": resource.portable,
                "appears_edible": resource.edible,
            })

    entities: list[dict[str, Any]] = []
    for npc in world.npcs.values():
        distance = math.hypot(npc.x - agent.x, npc.y - agent.y)
        if distance <= radius and has_line_of_sight(world, ax, ay, int(npc.x), int(npc.y)):
            classification = npc.kind if distance <= 4 else ("large animal" if npc.kind in {"deer", "wolf"} else "small moving creature")
            entities.append({
                "id": npc.id,
                "classification": classification,
                "distance": round(distance, 1),
                "direction": _direction(npc.x - agent.x, npc.y - agent.y),
                "behavior": npc.state,
                "danger_signs": npc.dangerous and distance <= 5,
            })

    shelter = world.nearby_shelter(agent.x, agent.y, 3.0)
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

    hunger_deficit = round(agent.hunger, 1)
    body = {
        "position": {"subjective_origin": "self"},
        "facing": agent.facing,
        "movement": "sleeping" if agent.sleeping else ("active" if agent.current_action else "stationary"),
        "health_reserve": round(agent.health, 1),
        "energy_reserve": round(agent.energy, 1),
        "hunger_deficit": hunger_deficit,
        "satiety": round(100.0 - agent.hunger, 1),
        "hydration_reserve": round(agent.hydration, 1),
        "sleep_pressure": round(agent.sleep_pressure, 1),
        "temperature_c": round(agent.body_temperature_c, 2),
        "pain": round(agent.pain, 1),
        "inventory": dict(agent.inventory),
        "inventory_capacity": agent.inventory_capacity,
        "key_items": [item.display_name for item in agent.key_items.values()],
        "scale_explanation": {
            "hunger_deficit": "0 is fully fed; 100 is starving",
            "satiety": "100 is fully fed; 0 is starving",
            "health_energy_hydration": "100 is best; 0 is critical",
            "sleep_pressure_and_pain": "0 is best; 100 is critical",
        },
        "health": round(agent.health, 1),
        "energy": round(agent.energy, 1),
        "hunger": hunger_deficit,
        "hydration": round(agent.hydration, 1),
    }
    cognition_summary = {
        "key_item_ids": sorted(agent.key_items),
        "task_count": len(agent.tasks),
        "proposed_task_titles": [task.title for task in sorted(agent.tasks.values(), key=lambda item: item.priority)[:4]],
        "note_count": len(agent.notes),
        "map_marker_count": len(agent.map_markers),
        "belief_count": len(agent.beliefs),
        "recent_episode_count": len(agent.short_term_episodes),
    }

    return {
        "awakening": agent.awakening.narrative if not agent.awakening.presented else None,
        "body": body,
        "cognitive_tools": cognition_summary,
        "drive_labels": drive_labels(agent),
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
            "tile_count": len(agent.known_terrain),
            "nearby_known_tiles": [
                {"x": int(key.split(",")[0]) - ax, "y": int(key.split(",")[1]) - ay, "terrain": terrain}
                for key, terrain in sorted(
                    agent.known_terrain.items(),
                    key=lambda item: abs(int(item[0].split(",")[0]) - ax) + abs(int(item[0].split(",")[1]) - ay),
                )[:KNOWN_TILE_SUMMARY_LIMIT]
            ],
        },
        "belief_summary": _belief_summary(agent),
        "personality_traits": agent.personality_traits,
        "recent_events": [_safe_event_summary(event) for event in agent.recent_events[-10:]],
        "last_action_result": _safe_event_summary(agent.recent_events[-1]) if agent.recent_events else None,
    }
