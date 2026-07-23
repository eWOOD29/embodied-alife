from __future__ import annotations

from typing import Any

from app.simulation.agent import AgentState
from app.simulation.world import Terrain, WorldState

INTERACTION_RADIUS = 2.2
EAT_HUNGER_THRESHOLD = 25.0
URGENT_HUNGER_THRESHOLD = 65.0
FOOD_RESERVE_TARGET = 3


def build_action_affordances(
    world: WorldState,
    agent: AgentState,
    perception: dict[str, Any],
) -> dict[str, Any]:
    """Translate deterministic controller constraints into compact LLM guidance."""
    hunger_deficit = float(agent.hunger)
    satiety = max(0.0, 100.0 - hunger_deficit)
    eating_recommended = hunger_deficit >= EAT_HUNGER_THRESHOLD
    hunger_urgent = hunger_deficit >= URGENT_HUNGER_THRESHOLD

    inventory = dict(agent.inventory)
    edible_inventory = {
        key: quantity
        for key, quantity in inventory.items()
        if quantity > 0 and key in {"berry", "edible_plant"}
    }
    edible_units = sum(edible_inventory.values())

    targets: dict[str, dict[str, Any]] = {}
    for obj in perception.get("visible_objects", []):
        distance = float(obj.get("distance", 999.0))
        # Real perceptions always include quantity. Treat omitted quantity in older
        # fixtures/compatible adapters as present rather than silently depleted.
        quantity = int(obj.get("quantity", 1))
        is_edible = bool(obj.get("appears_edible")) and quantity > 0
        can_collect_food = not is_edible or edible_units < FOOD_RESERVE_TARGET or hunger_urgent
        executable: list[str] = []
        if distance <= INTERACTION_RADIUS:
            executable.append("inspect")
        if (
            distance <= INTERACTION_RADIUS
            and (obj.get("portable") or obj.get("kind") == "berry_bush")
            and can_collect_food
        ):
            executable.append("pick_up")
        if distance <= INTERACTION_RADIUS and is_edible and eating_recommended:
            executable.append("eat")

        requires_move_to_for = [
            action
            for action in ("inspect", "pick_up", "eat")
            if action not in executable
            and distance > INTERACTION_RADIUS
            and (
                action == "inspect"
                or (
                    action == "pick_up"
                    and (obj.get("portable") or obj.get("kind") == "berry_bush")
                    and can_collect_food
                )
                or (action == "eat" and is_edible and eating_recommended)
            )
        ]
        targets[obj["id"]] = {
            "kind": obj.get("kind"),
            "distance": distance,
            "direction": obj.get("direction"),
            "quantity": quantity,
            "portable": bool(obj.get("portable")),
            "appears_edible": bool(obj.get("appears_edible")),
            "depleted": quantity <= 0,
            "food_collection_recommended": can_collect_food if is_edible else None,
            "executable_now": executable,
            "requires_move_to_for": requires_move_to_for,
            "approach_action": "move_to" if requires_move_to_for else None,
        }

    for entity in perception.get("visible_entities", []):
        distance = float(entity.get("distance", 999.0))
        targets[entity["id"]] = {
            "kind": entity.get("classification"),
            "distance": distance,
            "direction": entity.get("direction"),
            "danger_signs": bool(entity.get("danger_signs")),
            "executable_now": ["inspect"] if distance <= INTERACTION_RADIUS else [],
            "requires_move_to_for": ["inspect"] if distance > INTERACTION_RADIUS else [],
            "approach_action": "move_to" if distance > INTERACTION_RADIUS else None,
        }

    ax, ay = int(round(agent.x)), int(round(agent.y))
    underfoot = world.tile(ax, ay)
    can_build = (
        underfoot == Terrain.BUILD_AREA
        and inventory.get("branch", 0) >= 3
        and inventory.get("stone", 0) >= 2
        and world.nearby_shelter(agent.x, agent.y, 2.0) is None
    )

    return {
        "interaction_radius": INTERACTION_RADIUS,
        "currently_available_action_names": perception.get("available_actions", []),
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
        "can_drink_now": "drink" in perception.get("available_actions", []),
        "can_build_now": can_build,
        "build_requirements": {
            "required": {"branch": 3, "stone": 2},
            "underfoot": underfoot.value,
        },
        "guidance": [
            "Treat executable_now as a hard constraint for target-specific actions.",
            "Use move_to only when the requested target action appears under requires_move_to_for.",
            "Hunger is a deficit: low numbers mean well-fed, not hungry.",
            "Do not eat unless need_semantics.eating_recommended is true.",
            "Look is a stationary survey. Repeating look without movement does not explore or reveal a new area.",
            "After one unchanged look, choose a legal move, move_to, or another productive action instead of looking again.",
            "A missing target ID is unavailable or depleted; do not act on stale beliefs about it.",
            "Do not repeat an action/target pair that recently failed unless new world evidence changes its availability.",
            "The deterministic controller remains authoritative and may correct an invalid proposal.",
        ],
    }
