from __future__ import annotations

from typing import Any

from app.simulation.agent import AgentState
from app.simulation.safe_state import exact_dict, finite, finite_pair, records, strict_text
from app.simulation.world import NPC, WorldState


def resolve_npc_interactions(world: WorldState, agent: AgentState, dt: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    safe_dt = finite(dt, None, minimum=0.0, maximum=3600.0)
    agent_position = finite_pair(getattr(agent, "x", None), getattr(agent, "y", None))
    health = finite(getattr(agent, "health", None), None, minimum=0.0, maximum=1_000_000.0)
    pain = finite(getattr(agent, "pain", None), None, minimum=0.0, maximum=100.0)
    sim_time = finite(getattr(world, "sim_time", None), None, minimum=0.0)
    if getattr(agent, "alive", None) is not True or safe_dt is None or safe_dt <= 0 or agent_position is None:
        return events

    current_action = exact_dict(getattr(agent, "current_action", None))
    current_action_name = current_action.get("action") if type(current_action.get("action")) is str else None
    for npc in records(getattr(world, "npcs", None), NPC):
        npc_position = finite_pair(npc.x, npc.y)
        npc_health = finite(npc.health, None, minimum=0.0, maximum=1_000_000.0)
        npc_id = strict_text(npc.id, maximum=160)
        npc_kind = strict_text(npc.kind, maximum=80)
        if npc_position is None or npc_health is None or npc_health <= 0 or npc_id is None or npc_kind is None:
            continue
        distance = ((npc_position[0] - agent_position[0]) ** 2 + (npc_position[1] - agent_position[1]) ** 2) ** 0.5
        if npc.dangerous is True and distance < 1.35 and current_action_name != "flee":
            damage = 4.0 * safe_dt
            if health is not None:
                health = max(0.0, health - damage)
                agent.health = health
            if pain is not None:
                pain = min(100.0, pain + damage * 2)
                agent.pain = pain
            if sim_time is not None:
                agent.last_damage_time = sim_time
            events.append(
                {
                    "kind": "damage",
                    "message": f"A {npc_kind} attacked Ari for {damage:.1f} damage.",
                    "importance": 0.95,
                    "data": {"npc_id": npc_id, "damage": damage},
                }
            )
            if health is not None and health <= 0:
                agent.alive = False
                events.append({"kind": "death", "message": "Ari died from injuries.", "importance": 1.0, "data": {}})
    return events
