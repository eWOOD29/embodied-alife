from __future__ import annotations

from typing import Any

from app.simulation.agent import AgentState
from app.simulation.world import Terrain, WorldState


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
        if distance <= 2.2:
            executable.append("inspect")
        if distance <= 1.6 and (obj.get("portable") or obj.get("kind") == "berry_bush"):
            executable.append("pick_up")
        if distance <= 1.6 and obj.get("appears_edible"):
            executable.append("eat")
        targets[obj["id"]] = {
            "kind": obj.get("kind"),
            "distance": distance,
            "direction": obj.get("direction"),
            "executable_now": executable,
            "approach_action": None if executable else "move_to",
        }

    for entity in perception.get("visible_entities", []):
        distance = float(entity.get("distance", 999.0))
        targets[entity["id"]] = {
            "kind": entity.get("classification"),
            "distance": distance,
            "direction": entity.get("direction"),
            "danger_signs": bool(entity.get("danger_signs")),
            "executable_now": ["inspect"] if distance <= 2.2 else [],
            "approach_action": None if distance <= 2.2 else "move_to",
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
            "Choose inspect, pick_up, eat, drink, or build only when this map says it is executable now.",
            "Use move_to first for a visible target whose approach_action is move_to.",
            "Do not assume a proposed action succeeds; the deterministic controller remains authoritative.",
        ],
    }
