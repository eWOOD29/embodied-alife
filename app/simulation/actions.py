from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.llm.schemas import ActionDecision
from app.simulation.agent import AgentState
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
    "north": (0, -1),
    "northeast": (1, -1),
    "east": (1, 0),
    "southeast": (1, 1),
    "south": (0, 1),
    "southwest": (-1, 1),
    "west": (-1, 0),
    "northwest": (-1, -1),
}


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
            if math.hypot(resource.x - agent.x, resource.y - agent.y) > 1.6:
                return ActionResult(False, action, "out_of_reach", "The resource is too far away.")
            if not resource.portable:
                # Berry bushes can be harvested into berries.
                if resource.kind != "berry_bush":
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
                return ActionResult(
                    False,
                    action,
                    "missing_materials",
                    f"A shelter needs 3 branches and 2 stones; inventory has {agent.inventory.get('branch', 0)} branches and {agent.inventory.get('stone', 0)} stones.",
                )
            if world.nearby_shelter(agent.x, agent.y, 2.0):
                return ActionResult(False, action, "already_built", "A shelter already occupies this location.")
            duration = max(12.0, duration)
        elif action == "drop":
            if not decision.target_id or agent.inventory.get(decision.target_id, 0) <= 0:
                return ActionResult(False, action, "item_missing", "The requested inventory item is unavailable.")
        elif action == "inspect" and decision.target_id:
            if not self._target_near(decision.target_id, world, agent, 2.2):
                return ActionResult(False, action, "out_of_reach", "The target is not close enough to inspect.")
        elif action == "sleep":
            duration = max(15.0, duration)
            agent.sleeping = True
        elif action not in {"look", "rest", "speak", "wait"}:
            return ActionResult(False, action, "unsupported_action", "The action is not supported by this controller.")

        self.execution = ActionExecution(
            action=action,
            target_id=decision.target_id,
            remaining=duration,
            total_duration=duration,
            path=path,
            direction=decision.direction,
            started_at=world.sim_time,
            metadata=metadata,
        )
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

        # Movement completes as soon as the goal is reached; other actions use their duration.
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
        action = execution.action
        target_id = execution.target_id
        if action in {"move", "move_to", "flee"}:
            return ActionResult(True, action, "completed", "The body reached the destination.", {"position": [round(agent.x, 2), round(agent.y, 2)]})
        if action == "pick_up":
            resource = world.resources.get(target_id or "")
            if not resource or resource.quantity <= 0 or math.hypot(resource.x - agent.x, resource.y - agent.y) > 1.6:
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
                if kind == "berry":
                    nutrition, energy = 22.0, 5.0
            else:
                resource = world.resources[kind]
                resource.quantity -= 1
                resource.last_harvest_time = world.sim_time
                nutrition, energy = resource.nutrition, resource.energy
                kind = resource.kind
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
            agent.remove_item("branch", 3)
            agent.remove_item("stone", 2)
            shelter_id = f"shelter_{len(world.shelters) + 1:02d}"
            shelter = Shelter(shelter_id, int(round(agent.x)), int(round(agent.y)), quality=0.65)
            world.shelters[shelter_id] = shelter
            agent.known_locations[shelter_id] = {"x": shelter.x, "y": shelter.y, "certainty": 1.0, "last_seen": world.sim_time}
            return ActionResult(True, action, "built", "A basic shelter was built from branches and stones.", shelter.to_dict())
        if action == "drop":
            if not target_id or not agent.remove_item(target_id, 1):
                return ActionResult(False, action, "item_missing", "The item is no longer in inventory.")
            rid = f"dropped_{target_id}_{int(world.sim_time * 10)}"
            from app.simulation.world import Resource

            is_edible = target_id in {"berry", "edible_plant"}
            world.resources[rid] = Resource(
                rid, target_id, int(round(agent.x)), int(round(agent.y)),
                edible=is_edible, nutrition=22.0 if target_id == "berry" else (12.0 if is_edible else 0.0),
                energy=5.0 if target_id == "berry" else (2.0 if is_edible else 0.0),
            )
            return ActionResult(True, action, "dropped", f"Dropped 1 {target_id}.")
        if action == "inspect":
            agent.beliefs[f"inspection:{target_id or 'surroundings'}"] = f"Inspected at simulation time {world.sim_time:.1f}; observations remain provisional."
            return ActionResult(True, action, "inspected", f"Inspected {target_id or 'the surroundings'}.")
        if action == "look":
            return ActionResult(True, action, "observed", "Ari deliberately surveyed the nearby area.")
        if action == "speak":
            return ActionResult(True, action, "spoken", "Ari spoke aloud; nearby entities may or may not respond.")
        return ActionResult(True, action, "completed", f"Action {action} completed.")

    def _resolve_goal(self, decision: ActionDecision, world: WorldState, agent: AgentState) -> tuple[int, int] | None:
        if decision.action == "flee":
            dangers = [npc for npc in world.npcs.values() if npc.dangerous]
            if not dangers:
                return None
            nearest = min(dangers, key=lambda npc: math.hypot(npc.x - agent.x, npc.y - agent.y))
            dx, dy = agent.x - nearest.x, agent.y - nearest.y
            norm = max(0.001, math.hypot(dx, dy))
            for distance in (8, 6, 4, 2):
                goal = (int(round(agent.x + dx / norm * distance)), int(round(agent.y + dy / norm * distance)))
                if world.is_walkable(*goal):
                    return goal
        if decision.target_id:
            resource = world.resources.get(decision.target_id)
            if resource:
                return self._adjacent_walkable(world, resource.x, resource.y, agent)
            npc = world.npcs.get(decision.target_id)
            if npc:
                return self._adjacent_walkable(world, int(npc.x), int(npc.y), agent)
            location = agent.known_locations.get(decision.target_id)
            if location:
                return int(location["x"]), int(location["y"])
        if decision.direction:
            dx, dy = DIRECTION_DELTAS[decision.direction]
            distance = max(1, min(12, int(round(decision.duration_seconds * agent.movement_speed))))
            for dist in range(distance, 0, -1):
                goal = (int(round(agent.x)) + dx * dist, int(round(agent.y)) + dy * dist)
                if world.is_walkable(*goal):
                    return goal
        return None

    @staticmethod
    def _adjacent_walkable(world: WorldState, x: int, y: int, agent: AgentState) -> tuple[int, int] | None:
        candidates = [(x, y)] + [(x + dx, y + dy) for dx, dy in DIRECTION_DELTAS.values()]
        valid = [p for p in candidates if world.is_walkable(*p)]
        return min(valid, key=lambda p: math.hypot(p[0] - agent.x, p[1] - agent.y)) if valid else None

    @staticmethod
    def _near_water(world: WorldState, agent: AgentState) -> bool:
        ax, ay = int(round(agent.x)), int(round(agent.y))
        return any(
            world.is_water(x, y)
            for y in range(max(0, ay - 1), min(world.size, ay + 2))
            for x in range(max(0, ax - 1), min(world.size, ax + 2))
        )

    @staticmethod
    def _find_edible(target_id: str | None, world: WorldState, agent: AgentState) -> tuple[str, str] | None:
        if target_id and agent.inventory.get(target_id, 0) > 0 and target_id in {"berry", "edible_plant"}:
            return "inventory", target_id
        for kind in ("berry", "edible_plant"):
            if agent.inventory.get(kind, 0) > 0:
                return "inventory", kind
        if target_id and target_id in world.resources:
            resource = world.resources[target_id]
            if resource.edible and resource.quantity > 0 and math.hypot(resource.x - agent.x, resource.y - agent.y) <= 1.6:
                return "world", resource.id
        for resource in world.resources.values():
            if resource.edible and resource.quantity > 0 and math.hypot(resource.x - agent.x, resource.y - agent.y) <= 1.6:
                return "world", resource.id
        return None

    @staticmethod
    def _target_near(target_id: str, world: WorldState, agent: AgentState, radius: float) -> bool:
        if target_id in world.resources:
            r = world.resources[target_id]
            return math.hypot(r.x - agent.x, r.y - agent.y) <= radius
        if target_id in world.npcs:
            n = world.npcs[target_id]
            return math.hypot(n.x - agent.x, n.y - agent.y) <= radius
        if target_id in agent.known_locations:
            p = agent.known_locations[target_id]
            return math.hypot(p["x"] - agent.x, p["y"] - agent.y) <= radius
        return False
