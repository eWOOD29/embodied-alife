from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from app.simulation.agent import AgentState
from app.simulation.world import WorldState


@dataclass(slots=True)
class ActionExecution:
    action: str
    target_id: str | None
    remaining: float
    total_duration: float
    path: list[tuple[int, int]] = field(default_factory=list)
    direction: str | None = None
    started_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = [list(p) for p in self.path]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionExecution":
        copied = dict(data)
        copied["path"] = [tuple(p) for p in copied.get("path", [])]
        return cls(**copied)


def astar(world: WorldState, start: tuple[int, int], goal: tuple[int, int], max_nodes: int = 5000) -> list[tuple[int, int]]:
    if not world.is_walkable(*goal):
        return []
    frontier: list[tuple[float, int, tuple[int, int]]] = [(0.0, 0, start)]
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    cost: dict[tuple[int, int], float] = {start: 0.0}
    counter = 0
    while frontier and len(came_from) <= max_nodes:
        _, _, current = heapq.heappop(frontier)
        if current == goal:
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            nxt = (current[0] + dx, current[1] + dy)
            if not world.is_walkable(*nxt):
                continue
            step = 1.414 if dx and dy else 1.0
            terrain = world.tile(*nxt).value
            terrain_cost = 1.35 if terrain in {"forest", "shallow_water"} else 1.0
            new_cost = cost[current] + step * terrain_cost
            if nxt not in cost or new_cost < cost[nxt]:
                cost[nxt] = new_cost
                counter += 1
                priority = new_cost + math.hypot(goal[0] - nxt[0], goal[1] - nxt[1])
                heapq.heappush(frontier, (priority, counter, nxt))
                came_from[nxt] = current
    if goal not in came_from:
        return []
    path: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = goal
    while cur and cur != start:
        path.append(cur)
        cur = came_from[cur]
    path.reverse()
    return path


def effective_speed(agent: AgentState) -> float:
    multiplier = 1.0
    if agent.energy < 20:
        multiplier *= 0.55
    if agent.health < 40:
        multiplier *= 0.65
    if agent.pain > 50:
        multiplier *= 0.75
    return max(0.25, agent.movement_speed * multiplier)


def move_along_path(agent: AgentState, world: WorldState, execution: ActionExecution, dt: float) -> float:
    distance_budget = effective_speed(agent) * dt
    moved = 0.0
    while execution.path and distance_budget > 0:
        tx, ty = execution.path[0]
        dx, dy = tx - agent.x, ty - agent.y
        distance = math.hypot(dx, dy)
        if distance < 0.05:
            agent.x, agent.y = float(tx), float(ty)
            execution.path.pop(0)
            continue
        step = min(distance, distance_budget)
        nx = agent.x + dx / distance * step
        ny = agent.y + dy / distance * step
        if not world.is_walkable(int(round(nx)), int(round(ny))):
            execution.path.clear()
            break
        agent.x, agent.y = nx, ny
        moved += step
        distance_budget -= step
        agent.facing = _facing(dx, dy)
        if step >= distance - 1e-6:
            agent.x, agent.y = float(tx), float(ty)
            execution.path.pop(0)
    return moved


def _facing(dx: float, dy: float) -> str:
    if abs(dx) > abs(dy) * 1.8:
        return "east" if dx > 0 else "west"
    if abs(dy) > abs(dx) * 1.8:
        return "south" if dy > 0 else "north"
    return ("south" if dy > 0 else "north") + ("east" if dx > 0 else "west")
