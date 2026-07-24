from __future__ import annotations

from typing import Any

from app.serialization import finite_number
from app.simulation.agent import AgentState
from app.simulation.world import Terrain, WorldState

INTERACTION_RADIUS = 2.2
EAT_HUNGER_THRESHOLD = 25.0
URGENT_HUNGER_THRESHOLD = 65.0
FOOD_RESERVE_TARGET = 3
TARGET_LIMIT = 64
INVENTORY_LIMIT = 64


def _text(value: Any, limit: int = 160) -> str:
    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)[:limit]
    return ""


def _number(
    value: Any,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    return finite_number(value, default, minimum=minimum, maximum=maximum)


def _quantity(value: Any, default: int | None = None) -> int | None:
    number = _number(value, None, minimum=0.0, maximum=1_000_000.0)
    if number is None:
        return default
    return int(number)


def _flag(value: Any) -> bool:
    return value is True


def _mapping(value: Any) -> dict[Any, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value[:TARGET_LIMIT])
    return []


def _inventory(value: Any) -> dict[str, int]:
    source = _mapping(value)
    result: dict[str, int] = {}
    for index, (raw_key, raw_quantity) in enumerate(source.items()):
        if index >= INVENTORY_LIMIT:
            break
        key = _text(raw_key, 80)
        quantity = _quantity(raw_quantity)
        if key and quantity is not None:
            result[key] = quantity
    return result


def _position(world: WorldState, agent: AgentState) -> tuple[float, float] | None:
    maximum = _number(getattr(world, "size", None), None, minimum=1.0, maximum=1_000_000.0)
    x = _number(getattr(agent, "x", None))
    y = _number(getattr(agent, "y", None))
    if maximum is None or x is None or y is None:
        return None
    upper = maximum - 1.0
    if x < 0.0 or y < 0.0 or x > upper or y > upper:
        return None
    return x, y


def _available_actions(perception: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for raw in _sequence(perception.get("available_actions")):
        action = _text(raw, 48)
        if action and action not in result:
            result.append(action)
        if len(result) >= 32:
            break
    return result


def build_action_affordances(
    world: WorldState,
    agent: AgentState,
    perception: dict[str, Any],
) -> dict[str, Any]:
    """Translate deterministic constraints using only normalized local values."""
    safe_perception = perception if isinstance(perception, dict) else {}

    hunger_deficit = _number(getattr(agent, "hunger", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
    satiety = max(0.0, 100.0 - hunger_deficit)
    eating_recommended = hunger_deficit >= EAT_HUNGER_THRESHOLD
    hunger_urgent = hunger_deficit >= URGENT_HUNGER_THRESHOLD

    inventory = _inventory(getattr(agent, "inventory", None))
    edible_inventory = {
        key: quantity
        for key, quantity in inventory.items()
        if quantity > 0 and key in {"berry", "edible_plant"}
    }
    edible_units = sum(edible_inventory.values())
    available_actions = _available_actions(safe_perception)

    targets: dict[str, dict[str, Any]] = {}
    visible_objects = _sequence(safe_perception.get("visible_objects"))
    for raw in visible_objects[:TARGET_LIMIT]:
        if not isinstance(raw, dict):
            continue
        target_id = _text(raw.get("id"), 160)
        if not target_id or target_id in targets:
            continue
        distance = _number(raw.get("distance"), None, minimum=0.0, maximum=1_000_000.0)
        quantity = _quantity(raw.get("quantity"), 1 if "quantity" not in raw else None)
        portable = _flag(raw.get("portable"))
        kind = _text(raw.get("kind"), 80)
        appears_edible = _flag(raw.get("appears_edible"))
        is_edible = appears_edible and quantity is not None and quantity > 0
        can_collect_food = not is_edible or edible_units < FOOD_RESERVE_TARGET or hunger_urgent
        in_range = distance is not None and distance <= INTERACTION_RADIUS
        out_of_range = distance is not None and distance > INTERACTION_RADIUS
        executable: list[str] = []
        if in_range:
            executable.append("inspect")
        if in_range and (portable or kind == "berry_bush") and can_collect_food and quantity is not None and quantity > 0:
            executable.append("pick_up")
        if in_range and is_edible and eating_recommended:
            executable.append("eat")

        requires_move_to_for: list[str] = []
        if out_of_range:
            requires_move_to_for.append("inspect")
            if (portable or kind == "berry_bush") and can_collect_food and quantity is not None and quantity > 0:
                requires_move_to_for.append("pick_up")
            if is_edible and eating_recommended:
                requires_move_to_for.append("eat")

        targets[target_id] = {
            "kind": kind or None,
            "distance": round(distance, 3) if distance is not None else None,
            "distance_known": distance is not None,
            "direction": _text(raw.get("direction"), 48) or None,
            "quantity": quantity,
            "quantity_known": quantity is not None,
            "portable": portable,
            "appears_edible": appears_edible,
            "depleted": quantity <= 0 if quantity is not None else None,
            "food_collection_recommended": can_collect_food if is_edible else None,
            "executable_now": executable,
            "requires_move_to_for": requires_move_to_for,
            "approach_action": "move_to" if requires_move_to_for else None,
        }

    visible_entities = _sequence(safe_perception.get("visible_entities"))
    for raw in visible_entities[:TARGET_LIMIT]:
        if not isinstance(raw, dict):
            continue
        target_id = _text(raw.get("id"), 160)
        if not target_id or target_id in targets:
            continue
        distance = _number(raw.get("distance"), None, minimum=0.0, maximum=1_000_000.0)
        in_range = distance is not None and distance <= INTERACTION_RADIUS
        out_of_range = distance is not None and distance > INTERACTION_RADIUS
        targets[target_id] = {
            "kind": _text(raw.get("classification"), 80) or None,
            "distance": round(distance, 3) if distance is not None else None,
            "distance_known": distance is not None,
            "direction": _text(raw.get("direction"), 48) or None,
            "danger_signs": _flag(raw.get("danger_signs")),
            "executable_now": ["inspect"] if in_range else [],
            "requires_move_to_for": ["inspect"] if out_of_range else [],
            "approach_action": "move_to" if out_of_range else None,
        }

    position = _position(world, agent)
    underfoot: Terrain | None = None
    nearby_shelter = None
    if position is not None:
        agent_x, agent_y = position
        try:
            underfoot = world.tile(int(round(agent_x)), int(round(agent_y)))
        except Exception:
            underfoot = None
        try:
            nearby_shelter = world.nearby_shelter(agent_x, agent_y, 2.0)
        except Exception:
            nearby_shelter = None
    can_build = (
        position is not None
        and underfoot == Terrain.BUILD_AREA
        and inventory.get("branch", 0) >= 3
        and inventory.get("stone", 0) >= 2
        and nearby_shelter is None
    )

    return {
        "interaction_radius": INTERACTION_RADIUS,
        "position_known": position is not None,
        "currently_available_action_names": available_actions,
        "target_constraints": targets,
        "inventory": inventory,
        "inventory_edibles": edible_inventory,
        "need_semantics": {
            "hunger_deficit": round(hunger_deficit, 2),
            "hunger_scale": "0 means fully fed; 100 means starving",
            "satiety": round(satiety, 2),
            "satiety_scale": "100 means fully fed; 0 means starving",
            "eating_recommended": eating_recommended,
            "hunger_urgent": hunger_urgent,
            "eat_hunger_threshold": EAT_HUNGER_THRESHOLD,
        },
        "food_policy": {
            "edible_inventory_units": edible_units,
            "reserve_target_units": FOOD_RESERVE_TARGET,
            "can_eat_now": eating_recommended and bool(edible_inventory),
            "collect_more_food": edible_units < FOOD_RESERVE_TARGET or hunger_urgent,
            "instruction": "Do not eat merely because food exists. Eat only when eating_recommended is true; otherwise preserve a small reserve and pursue another need or exploration goal.",
        },
        "can_eat_from_inventory": eating_recommended and bool(edible_inventory),
        "can_drink_now": "drink" in available_actions,
        "can_build_now": can_build,
        "build_requirements": {
            "required": {"branch": 3, "stone": 2},
            "underfoot": underfoot.value if isinstance(underfoot, Terrain) else "unknown",
        },
        "guidance": [
            "Treat executable_now as a hard constraint for target-specific actions.",
            "Use move_to only when the requested target action appears under requires_move_to_for.",
            "When position_known or distance_known is false, do not infer direction, distance, reachability, or shelter proximity.",
            "Hunger is a deficit: low numbers mean well-fed, not hungry.",
            "Do not eat unless need_semantics.eating_recommended is true.",
            "Look is a stationary survey. Repeating look without movement does not explore or reveal a new area.",
            "After one unchanged look, choose a legal move, move_to, or another productive action instead of looking again.",
            "A missing target ID is unavailable or depleted; do not act on stale beliefs about it.",
            "Do not repeat an action/target pair that recently failed unless new world evidence changes its availability.",
            "The deterministic controller remains authoritative and may correct an invalid proposal.",
        ],
    }
