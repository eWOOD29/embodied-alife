from __future__ import annotations

import math
from typing import Any

from app.simulation.agent import AgentState
from app.simulation.world import WorldState


def resolve_npc_interactions(world: WorldState, agent: AgentState, dt: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not agent.alive:
        return events
    for npc in world.npcs.values():
        distance = math.hypot(npc.x - agent.x, npc.y - agent.y)
        if npc.dangerous and distance < 1.35 and agent.current_action and agent.current_action.get("action") != "flee":
            damage = 4.0 * dt
            agent.health = max(0.0, agent.health - damage)
            agent.pain = min(100.0, agent.pain + damage * 2)
            agent.last_damage_time = world.sim_time
            events.append(
                {
                    "kind": "damage",
                    "message": f"A {npc.kind} attacked Ari for {damage:.1f} damage.",
                    "importance": 0.95,
                    "data": {"npc_id": npc.id, "damage": damage},
                }
            )
            if agent.health <= 0:
                agent.alive = False
                events.append({"kind": "death", "message": "Ari died from injuries.", "importance": 1.0, "data": {}})
    return events
