from __future__ import annotations

from dataclasses import dataclass

from app.simulation.agent import AgentState
from app.simulation.world import Terrain, WorldState


@dataclass(slots=True)
class NeedTickResult:
    damage: float = 0.0
    messages: list[str] | None = None


def update_needs(agent: AgentState, world: WorldState, dt: float, moving: bool = False) -> NeedTickResult:
    messages: list[str] = []
    if not agent.alive:
        return NeedTickResult(messages=messages)

    shelter = world.nearby_shelter(agent.x, agent.y)
    terrain = world.tile(int(round(agent.x)), int(round(agent.y)))
    weather_exposure = {"clear": 0.0, "cloudy": -0.5, "rain": -2.5, "storm": -5.0}[world.weather]
    terrain_delta = -2.0 if terrain in {Terrain.SHALLOW_WATER, Terrain.DEEP_WATER} else 0.0
    shelter_bonus = 5.5 * shelter.quality if shelter else 0.0
    effective_ambient = world.ambient_temperature_c + weather_exposure + terrain_delta + shelter_bonus
    target_body_temp = 37.0 + max(-3.5, min(2.0, (effective_ambient - 18.0) * 0.06))
    agent.body_temperature_c += (target_body_temp - agent.body_temperature_c) * min(1.0, dt * 0.015)

    if agent.sleeping:
        agent.energy = min(100.0, agent.energy + dt * (0.10 + (0.05 if shelter else 0.0)))
        agent.sleep_pressure = max(0.0, agent.sleep_pressure - dt * (0.11 + (0.04 if shelter else 0.0)))
        agent.hunger = min(100.0, agent.hunger + dt * 0.012)
        agent.hydration = max(0.0, agent.hydration - dt * 0.018)
    else:
        energy_drain = 0.018 + (0.09 if moving else 0.0)
        if world.weather == "storm":
            energy_drain += 0.02
        agent.energy = max(0.0, agent.energy - dt * energy_drain)
        agent.hunger = min(100.0, agent.hunger + dt * 0.018)
        agent.hydration = max(0.0, agent.hydration - dt * 0.028)
        agent.sleep_pressure = min(100.0, agent.sleep_pressure + dt * 0.018)

    agent.grace_seconds_remaining = max(0.0, agent.grace_seconds_remaining - dt)
    damage = 0.0
    if agent.grace_seconds_remaining <= 0:
        if agent.hydration <= 4:
            damage += dt * 0.20
        if agent.hunger >= 98:
            damage += dt * 0.10
        if agent.energy <= 1:
            damage += dt * 0.07
        if agent.body_temperature_c < 34.5 or agent.body_temperature_c > 40.0:
            damage += dt * 0.16
    if damage > 0:
        agent.health = max(0.0, agent.health - damage)
        agent.pain = min(100.0, agent.pain + damage * 2)
        messages.append("Vital stress is damaging the body.")
    else:
        agent.pain = max(0.0, agent.pain - dt * 0.01)
    if agent.health <= 0:
        agent.alive = False
        agent.sleeping = False
        messages.append("The body has died.")
    return NeedTickResult(damage=damage, messages=messages)


def drive_labels(agent: AgentState) -> dict[str, str]:
    def high_bad(value: float) -> str:
        if value >= 85:
            return "critical"
        if value >= 65:
            return "high"
        if value >= 40:
            return "medium"
        return "low"

    def low_bad(value: float) -> str:
        if value <= 10:
            return "critical"
        if value <= 30:
            return "low"
        if value <= 60:
            return "medium"
        return "good"

    temp = "comfortable"
    if agent.body_temperature_c < 35.0:
        temp = "dangerously cold"
    elif agent.body_temperature_c < 36.2:
        temp = "cold"
    elif agent.body_temperature_c > 39.2:
        temp = "dangerously hot"
    elif agent.body_temperature_c > 37.8:
        temp = "hot"
    return {
        "health": low_bad(agent.health),
        "energy": low_bad(agent.energy),
        "hunger": high_bad(agent.hunger),
        "hydration": low_bad(agent.hydration),
        "sleep_pressure": high_bad(agent.sleep_pressure),
        "temperature": temp,
        "pain": high_bad(agent.pain),
    }
