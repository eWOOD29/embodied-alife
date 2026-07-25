from __future__ import annotations

import math
from types import SimpleNamespace
from itertools import islice
from typing import Any

from app.serialization import finite_number
from app.simulation.actions import ari_record_origin_is_safe
from app.simulation.integrity import seal_knowledge, verify_knowledge, verify_record
from app.simulation.agent import AgentState, AwakeningState
from app.simulation.belief_store import BeliefStore
from app.simulation.needs import drive_labels
from app.simulation.safe_state import builtin_dict_copy, builtin_dict_items, builtin_sequence
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
    if type(value) is str:
        text = value
    elif type(value) is int:
        text = str(value)
    elif type(value) is float:
        number = finite_number(value)
        if number is None:
            return ""
        text = str(number)
    elif type(value) is bool:
        text = "true" if value else "false"
    else:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:
    number = finite_number(value, default, minimum=minimum, maximum=maximum)
    return default if number is None else number


def _bounded_pairs(value: Any, *, count_limit: int, key_limit: int, value_limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, raw_value in builtin_dict_items(value, limit=count_limit):
        key = _truncate(raw_key, key_limit)
        if not key:
            continue
        if type(raw_value) in {int, float}:
            projected: Any = _safe_number(raw_value)
        elif type(raw_value) is bool:
            projected = raw_value
        else:
            projected = _truncate(raw_value, value_limit)
        result[key] = projected
    return result


def _known_tile_summaries(agent: AgentState, ax: int | None, ay: int | None) -> list[dict[str, Any]]:
    if ax is None or ay is None:
        return []
    records: list[tuple[int, int, int, str]] = []
    known_terrain = builtin_dict_copy(agent.known_terrain, limit=4096)
    for raw_key, raw_terrain in known_terrain.items():
        if not type(raw_key) is str or not verify_knowledge(agent, "terrain", raw_key, raw_terrain):
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
    beliefs = agent.beliefs if type(agent.beliefs) in {dict, BeliefStore} else {}
    verified_total = 0
    for index, (key, belief) in enumerate(beliefs.items()):
        if index >= 4096 or type(belief) is not dict and type(belief).__name__ != "BeliefValue" or not verify_record("belief", belief, agent):
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
    known_locations = builtin_dict_copy(agent.known_locations, limit=4096)
    for label, raw in known_locations.items():
        if type(raw) is not dict:
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
    if type(event) is not dict:
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


def _observation_position(world: WorldState, agent: AgentState) -> tuple[int, int, int, float, float] | None:
    world_size_number = _safe_number(getattr(world, "size", None), math.nan)
    world_size = int(world_size_number) if math.isfinite(world_size_number) and world_size_number >= 1 else 0
    raw_x = _safe_number(getattr(agent, "x", None), math.nan)
    raw_y = _safe_number(getattr(agent, "y", None), math.nan)
    if not (
        world_size > 0
        and math.isfinite(raw_x)
        and math.isfinite(raw_y)
        and 0.0 <= raw_x <= world_size - 1
        and 0.0 <= raw_y <= world_size - 1
    ):
        return None
    return world_size, int(round(raw_x)), int(round(raw_y)), raw_x, raw_y


def _terrain_observations(world: WorldState, ax: int, ay: int, world_size: int, radius: int) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    for y in range(max(0, ay - radius), min(world_size, ay + radius + 1)):
        for x in range(max(0, ax - radius), min(world_size, ax + radius + 1)):
            distance = math.hypot(x - ax, y - ay)
            if distance > radius or not has_line_of_sight(world, ax, ay, x, y):
                continue
            try:
                tile = world.tile(x, y)
            except Exception:
                continue
            if type(tile) is not Terrain:
                continue
            result.append((x, y, tile.value))
    return result


def _location_observation(x: int, y: int, terrain: str, sim_time: float | None) -> tuple[str, dict[str, Any]] | None:
    if terrain == Terrain.CAVE.value:
        identity, certainty = "cave_entrance", 1.0
    elif terrain == Terrain.BUILD_AREA.value:
        identity, certainty = "stable_clearing", 0.9
    elif terrain in {Terrain.SHALLOW_WATER.value, Terrain.DEEP_WATER.value}:
        identity, certainty = f"water_near_{x // 8}_{y // 8}", 0.8
    else:
        return None
    return identity, {"x": x, "y": y, "certainty": certainty, "last_seen": sim_time}


def _same_location_observation(existing: Any, observed: dict[str, Any]) -> bool:
    if type(existing) is not dict:
        return False
    return (
        type(existing.get("x")) is int
        and type(existing.get("y")) is int
        and type(existing.get("certainty")) in {int, float}
        and existing.get("x") == observed.get("x")
        and existing.get("y") == observed.get("y")
        and float(existing.get("certainty")) == float(observed.get("certainty"))
    )


def ingest_perception(world: WorldState, agent: AgentState, radius: int = 10) -> dict[str, int]:
    """Authoritatively ingest newly observed or materially changed Ari knowledge.

    This boundary is intentionally separate from projection. Unchanged observations do not
    mutate durable state and never invoke proof generation. Source identities are stable and
    do not depend on simulation time.
    """
    position = _observation_position(world, agent)
    if position is None:
        return {"explored_added": 0, "terrain_signed": 0, "locations_signed": 0}
    world_size, ax, ay, _, _ = position
    observations = _terrain_observations(world, ax, ay, world_size, radius)
    explored_store = agent.explored if type(agent.explored) is set else None
    terrain_store = agent.known_terrain if type(agent.known_terrain) is dict else None
    location_store = agent.known_locations if type(agent.known_locations) is dict else None
    sim_time = finite_number(getattr(world, "sim_time", None), None, minimum=0.0)
    explored_added = terrain_signed = locations_signed = 0
    location_observations: dict[str, dict[str, Any]] = {}

    for x, y, terrain in observations:
        key = f"{x},{y}"
        if explored_store is not None and key not in explored_store:
            explored_store.add(key)
            explored_added += 1
        if terrain_store is not None:
            exists = key in terrain_store
            existing = terrain_store.get(key)
            if not (exists and type(existing) is str and existing == terrain):
                terrain_store[key] = terrain
                if seal_knowledge(
                    agent, "terrain", key, terrain, "validated_perception",
                    source_ref=f"perception:terrain:{key}",
                ):
                    terrain_signed += 1
        location = _location_observation(x, y, terrain, sim_time)
        if location is not None:
            location_observations[location[0]] = location[1]

    if location_store is not None:
        for identity, observed in location_observations.items():
            exists = identity in location_store
            existing = location_store.get(identity)
            if exists and _same_location_observation(existing, observed):
                continue
            location_store[identity] = observed
            if seal_knowledge(
                agent, "location", identity, observed, "validated_perception",
                source_ref=f"perception:location:{identity}",
            ):
                locations_signed += 1

    return {
        "explored_added": explored_added,
        "terrain_signed": terrain_signed,
        "locations_signed": locations_signed,
    }


def observe(world: WorldState, agent: AgentState, radius: int = 10) -> dict[str, Any]:
    """Perform authoritative ingestion, then return a pure perception projection."""
    ingest_perception(world, agent, radius)
    return build_perception(world, agent, radius)


def build_perception(world: WorldState, agent: AgentState, radius: int = 10) -> dict[str, Any]:
    """Project current perception and Ari-known state without durable mutation."""
    position = _observation_position(world, agent)
    if position is None:
        world_size = 0
        ax = ay = None
        agent_x = agent_y = None
        position_known = False
        observations: list[tuple[int, int, str]] = []
    else:
        world_size, ax, ay, agent_x, agent_y = position
        position_known = True
        observations = _terrain_observations(world, ax, ay, world_size, radius)

    terrain_store = agent.known_terrain if type(agent.known_terrain) is dict else None
    location_store = agent.known_locations if type(agent.known_locations) is dict else None
    visible_tiles: list[dict[str, Any]] = []
    terrain_counts: dict[str, int] = {}
    if ax is not None and ay is not None:
        for x, y, terrain in observations:
            terrain_counts[terrain] = terrain_counts.get(terrain, 0) + 1
            visible_tiles.append({"offset_east": x - ax, "offset_south": y - ay, "terrain": terrain})

    objects: list[dict[str, Any]] = []
    resources = builtin_dict_copy(getattr(world, "resources", None), limit=4096)
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
    npcs = builtin_dict_copy(getattr(world, "npcs", None), limit=4096)
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
        inventory = builtin_dict_copy(agent.inventory, limit=4096)
        if any(obj["distance"] <= INTERACTION_RADIUS and obj["appears_edible"] for obj in objects) or any(
            type(inventory.get(key)) is int and inventory.get(key, 0) > 0
            for key in ("berry", "berry_bush", "edible_plant")
        ):
            affordances.append("eat")
        if any(
            world.is_water(x, y)
            for y in range(max(0, ay - 1), min(world_size, ay + 2))
            for x in range(max(0, ax - 1), min(world_size, ax + 2))
        ):
            affordances.append("drink")
        if any(type(value) is int and value > 0 for value in inventory.values()):
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
        item for item in builtin_dict_copy(agent.key_items, limit=4096).values()
        if verify_record("key_item", item, agent)
    ]
    safe_tasks = [
        task for task in builtin_dict_copy(agent.tasks, limit=4096).values()
        if ari_record_origin_is_safe("task", task, agent)
    ]
    safe_notes = [
        note for note in builtin_dict_copy(agent.notes, limit=4096).values()
        if ari_record_origin_is_safe("note", note, agent)
    ]
    safe_markers = [
        marker for marker in builtin_dict_copy(agent.map_markers, limit=4096).values()
        if ari_record_origin_is_safe("marker", marker, agent)
    ]
    safe_episodes = [
        episode for episode in builtin_dict_copy(agent.short_term_episodes, limit=4096).values()
        if verify_record("episode", episode, agent)
    ]

    body = {
        "position": {"subjective_origin": "self", "known": position_known},
        "facing": _truncate(getattr(agent, "facing", ""), 32),
        "movement": "sleeping" if getattr(agent, "sleeping", False) is True else ("active" if type(getattr(agent, "current_action", None)) is dict else "stationary"),
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

    recent_events = builtin_sequence(agent.recent_events, limit=4096)
    try:
        hour = round(_safe_number(world.hour()), 1)
    except Exception:
        hour = None
    try:
        light = round(_safe_number(world.daylight()), 2)
    except Exception:
        light = None
    return {
        "awakening": agent.awakening.narrative if type(agent.awakening) is AwakeningState and agent.awakening.presented is not True else None,
        "body": body,
        "cognitive_tools": cognition_summary,
        "drive_labels": drive_labels(safe_needs),
        "visible_objects": sorted(objects, key=lambda item: item["distance"])[:30],
        "visible_entities": sorted(entities, key=lambda item: item["distance"])[:12],
        "terrain_summary": terrain_counts,
        "local_tiles": visible_tiles,
        "underfoot": underfoot.value if type(underfoot) is Terrain else "unknown",
        "weather": _truncate(getattr(world, "weather", ""), 80),
        "ambient_temperature_c": _safe_number(getattr(world, "ambient_temperature_c", None), 0.0),
        "day": int(_safe_number(getattr(world, "day", None), 0.0)),
        "hour": hour,
        "light": light,
        "near_shelter": ({"present": True, "quality": round(_safe_number(getattr(shelter, "quality", None), 0.0, minimum=0.0, maximum=1.0), 3)} if shelter else None),
        "available_actions": sorted(set(affordances)),
        "known_locations": _known_location_summaries(agent, agent_x, agent_y),
        "previously_explored": {
            "tile_count": sum(
                1
                for key, value in islice(terrain_store.items(), 4096)
                if verify_knowledge(agent, "terrain", key, value)
            ) if terrain_store is not None else 0,
            "nearby_known_tiles": _known_tile_summaries(agent, ax, ay),
        },
        "belief_summary": _belief_summary(agent),
        "personality_traits": _bounded_pairs(getattr(agent, "personality_traits", None), count_limit=PERSONALITY_TRAIT_LIMIT, key_limit=PERSONALITY_KEY_LIMIT, value_limit=PERSONALITY_VALUE_LIMIT),
        "recent_events": [_safe_event_summary(event) for event in recent_events[-10:]],
        "last_action_result": _safe_event_summary(recent_events[-1]) if recent_events else None,
    }
