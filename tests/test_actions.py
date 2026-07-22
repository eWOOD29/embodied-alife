from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.llm.schemas import ActionDecision
from app.simulation.actions import ActionController
from app.simulation.agent import AgentState
from app.simulation.body import astar
from app.simulation.world import Resource, Terrain, WorldState


def complete(controller: ActionController, world: WorldState, agent: AgentState, seconds: float = 200):
    result = None
    elapsed = 0.0
    while controller.execution and elapsed < seconds:
        _, result, _ = controller.step(0.5, world, agent)
        elapsed += 0.5
    return result


def test_action_schema_rejects_invalid_action() -> None:
    with pytest.raises(ValidationError):
        ActionDecision(intent="bad", action="teleport", reason="not allowed")


def test_collision_and_pathfinding() -> None:
    world = WorldState.generate(77, 40)
    start = world.spawn
    rock = next((x, y) for y in range(world.size) for x in range(world.size) if world.tile(x, y) == Terrain.ROCK)
    assert astar(world, start, rock) == []
    open_goal = next((x, y) for y in range(world.size) for x in range(world.size) if world.is_walkable(x, y) and math.hypot(x-start[0], y-start[1]) > 5)
    assert astar(world, start, open_goal)


def test_inventory_limits() -> None:
    agent = AgentState(inventory_capacity=2)
    assert agent.add_item("stone")
    assert agent.add_item("branch")
    assert not agent.add_item("berry")
    assert agent.inventory_used == 2


def test_gather_and_eat() -> None:
    world = WorldState.generate(3, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1], hunger=80)
    resource = Resource("berry_bush_test", "berry_bush", int(agent.x), int(agent.y), quantity=2, max_quantity=2, portable=False, edible=True, nutrition=22, energy=5)
    world.resources[resource.id] = resource
    controller = ActionController()
    started = controller.start(ActionDecision(intent="gather", action="pick_up", target_id=resource.id, duration_seconds=0.5, reason="food"), world, agent)
    assert started.success
    result = complete(controller, world, agent)
    assert result and result.success
    assert agent.inventory["berry"] == 1
    before = agent.hunger
    assert controller.start(ActionDecision(intent="eat", action="eat", target_id="berry", duration_seconds=0.5, reason="hungry"), world, agent).success
    eaten = complete(controller, world, agent)
    assert eaten and eaten.success
    assert agent.hunger < before
    assert "berry" not in agent.inventory


def test_drinking_requires_water_and_restores_hydration() -> None:
    world = WorldState.generate(4, 40)
    water = next((x, y) for y in range(world.size) for x in range(world.size) if world.tile(x, y) == Terrain.SHALLOW_WATER)
    agent = AgentState(x=water[0], y=water[1], hydration=20)
    controller = ActionController()
    assert controller.start(ActionDecision(intent="drink", action="drink", duration_seconds=0.5, reason="thirst"), world, agent).success
    result = complete(controller, world, agent)
    assert result and result.success
    assert agent.hydration > 20


def test_sleep_is_durational() -> None:
    world = WorldState.generate(4, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1], energy=20, sleep_pressure=80)
    controller = ActionController()
    started = controller.start(ActionDecision(intent="sleep", action="sleep", duration_seconds=15, reason="tired"), world, agent)
    assert started.success and agent.sleeping
    controller.step(5, world, agent)
    assert agent.sleeping and controller.execution
    result = complete(controller, world, agent)
    assert result and result.reason == "woke"
    assert not agent.sleeping


def test_build_rules_and_material_consumption() -> None:
    world = WorldState.generate(10, 40)
    x, y = world.build_area
    agent = AgentState(x=x, y=y, inventory={"branch": 3, "stone": 2})
    controller = ActionController()
    decision = ActionDecision(intent="make cover", action="build", duration_seconds=12, reason="materials and stable ground")
    assert controller.start(decision, world, agent).success
    result = complete(controller, world, agent)
    assert result and result.success
    assert world.shelters
    assert agent.inventory == {}


def test_build_rejects_missing_materials() -> None:
    world = WorldState.generate(10, 40)
    x, y = world.build_area
    agent = AgentState(x=x, y=y, inventory={"branch": 1})
    controller = ActionController()
    result = controller.start(ActionDecision(intent="build", action="build", duration_seconds=12, reason="try"), world, agent)
    assert not result.success
    assert result.reason == "missing_materials"


def test_impossible_target_is_safe() -> None:
    world = WorldState.generate(1, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1])
    result = ActionController().start(ActionDecision(intent="go", action="move_to", target_id="not_real", reason="test"), world, agent)
    assert not result.success
    assert result.reason == "unknown_target"
