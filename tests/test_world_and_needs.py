from __future__ import annotations

from copy import deepcopy

from app.simulation.agent import AgentState
from app.simulation.needs import update_needs
from app.simulation.world import Shelter, Terrain, WorldState


def test_world_tick_progression_and_day_cycle() -> None:
    world = WorldState.generate(42, 40)
    world.tick(1300)
    assert world.sim_time == 1300
    assert world.day == 2
    assert world.weather in {"clear", "cloudy", "rain", "storm"}
    assert -10 < world.ambient_temperature_c < 30


def test_deterministic_seed_behavior() -> None:
    a = WorldState.generate(9988, 48)
    b = WorldState.generate(9988, 48)
    c = WorldState.generate(9989, 48)
    assert a.tiles == b.tiles
    assert [(r.kind, r.x, r.y) for r in a.resources.values()] == [(r.kind, r.x, r.y) for r in b.resources.values()]
    assert a.tiles != c.tiles or a.spawn != c.spawn


def test_needs_progress_awake_and_sleep() -> None:
    world = WorldState.generate(9, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1], energy=50, hunger=20, hydration=70, sleep_pressure=20)
    update_needs(agent, world, 30, moving=True)
    assert agent.energy < 50
    assert agent.hunger > 20
    assert agent.hydration < 70
    assert agent.sleep_pressure > 20
    before = deepcopy(agent)
    agent.sleeping = True
    update_needs(agent, world, 30, moving=False)
    assert agent.energy > before.energy
    assert agent.sleep_pressure < before.sleep_pressure


def test_temperature_and_shelter_effect() -> None:
    world = WorldState.generate(11, 40)
    world.weather = "storm"
    world.ambient_temperature_c = 2
    x, y = world.build_area
    exposed = AgentState(x=x, y=y, body_temperature_c=37)
    sheltered = AgentState(x=x, y=y, body_temperature_c=37)
    world.shelters["s"] = Shelter("s", x, y, quality=1.0)
    update_needs(sheltered, world, 120)
    del world.shelters["s"]
    update_needs(exposed, world, 120)
    assert sheltered.body_temperature_c > exposed.body_temperature_c


def test_critical_needs_damage_after_grace() -> None:
    world = WorldState.generate(2, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1], hydration=0, hunger=100, energy=0, grace_seconds_remaining=0)
    health = agent.health
    result = update_needs(agent, world, 10)
    assert result.damage > 0
    assert agent.health < health


def test_world_truth_not_copied_into_beliefs() -> None:
    world = WorldState.generate(5, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1])
    agent.beliefs["cave"] = "The cave is probably empty."
    assert world.truth_notes["cave"] != agent.beliefs["cave"]
    assert "wolf" in world.truth_notes["cave"]
