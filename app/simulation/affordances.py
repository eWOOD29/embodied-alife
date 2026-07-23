from __future__ import annotations

from typing import Any

from app.simulation.agent import AgentState
from app.simulation.world import Terrain, WorldState

INTERACTION_RADIUS = 2.2


def build_action_affordances(
    world: WorldState,
    agent: AgentState,
    perception: dict[str, Any],
) -> dict[str, Any]:
    """Translate deterministic controller constraints into compact LLM guidance."""
    targets: dict[str, dict[str, Any]] = {}
    for obj in perception.get("visible_objects", []):
        distance = float(obj.get("distance", 999.0))
        executable: list[str] = []
        if distance <= INTERACTION_RADIUS:
            executable.append("inspect")
        if distance <= INTERACTION_RADIUS and (obj.get("portable") or obj.get("kind") == "berry_bush"):
            executable.append("pick_up")
        if distance <= INTERACTION_RADIUS and obj.get("appears_edible") and int(obj.get("quantity", 0)) > 0:
            executable.append("eat")
        targets[obj["id"]] = {
            "kind": obj.get("kind"),
            "distance": distance,
            "direction": obj.get("direction"),
            "quantity": int(obj.get("quantity", 0)),
            "portable": bool(obj.get("portable")),
            "appears_edible": bool(obj.get("appears_edible")),
            "depleted": int(obj.get("quantity", 0)) <= 0,
            "executable_now": executable,
            "requires_move_to_for": [
                action
                for action in ("inspect", "pick_up", "eat")
                if action not in executable
                and (
                    action == "inspect"
                    or (action == "pick_up" and (obj.get("portable") or obj.get("kind") == "berry_bush"))
                    or (action == "eat" and obj.get("appears_edible") and int(obj.get("quantity", 0)) > 0)
                )
            ],
            "approach_action": "move_to" if distance > INTERACTION_RADIUS else None,
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

    inventory = dict(agent.inventory)
    edible_inventory = {
        key: quantity
        for key, quantity in inventory.items()
        if quantity > 0 and key in {"berry", "edible_plant"}
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
        "can_eat_from_inventory": bool(edible_inventory),
        "can_drink_now": "drink" in perception.get("available_actions", []),
        "can_build_now": can_build,
        "build_requirements": {
            "required": {"branch": 3, "stone": 2},
            "underfoot": underfoot.value,
        },
        "guidance": [
            "Treat executable_now as a hard constraint for target-specific actions.",
            "Use move_to only when the requested target action appears under requires_move_to_for.",
            "A missing target ID is unavailable or depleted; do not act on stale beliefs about it.",
            "Do not repeat an action/target pair that recently failed unless new world evidence changes its availability.",
            "The deterministic controller remains authoritative and may correct an invalid proposal.",
        ],
    }
