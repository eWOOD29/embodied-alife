from __future__ import annotations

from dataclasses import dataclass

from app.simulation.agent import AgentState
from app.simulation.safe_state import finite, finite_pair
from app.simulation.world import Shelter, Terrain, WorldState


@dataclass(slots=True)
class NeedTickResult:
    damage: float = 0.0
    messages: list[str] | None = None


def _update_numeric(agent: AgentState, name: str, transform) -> float | None:
    current = finite(getattr(agent, name, None), None, minimum=-1_000_000.0, maximum=1_000_000.0)
    if current is None:
        return None
    updated = transform(current)
    if isinstance(updated, (int, float)):
        setattr(agent, name, float(updated))
        return float(updated)
    return current


def update_needs(agent: AgentState, world: WorldState, dt: float, moving: bool = False) -> NeedTickResult:
    messages: list[str] = []
    safe_dt = finite(dt, None, minimum=0.0, maximum=3600.0)
    if getattr(agent, "alive", None) is not True or safe_dt is None or safe_dt <= 0:
        return NeedTickResult(messages=messages)

    position = finite_pair(getattr(agent, "x", None), getattr(agent, "y", None))
    shelter = world.nearby_shelter(*position) if position is not None else None
    terrain = world.tile(int(round(position[0])), int(round(position[1]))) if position is not None else Terrain.ROCK
    weather = world.weather if type(world.weather) is str and world.weather in {"clear", "cloudy", "rain", "storm"} else "clear"
    weather_exposure = {"clear": 0.0, "cloudy": -0.5, "rain": -2.5, "storm": -5.0}[weather]
    terrain_delta = -2.0 if terrain in {Terrain.SHALLOW_WATER, Terrain.DEEP_WATER} else 0.0
    shelter_quality = finite(shelter.quality, None, minimum=0.0, maximum=1.0) if type(shelter) is Shelter else None
    shelter_bonus = 5.5 * shelter_quality if shelter_quality is not None else 0.0
    ambient = finite(getattr(world, "ambient_temperature_c", None), None, minimum=-200.0, maximum=200.0)
    body_temp = finite(getattr(agent, "body_temperature_c", None), None, minimum=0.0, maximum=100.0)
    if ambient is not None and body_temp is not None:
        effective_ambient = ambient + weather_exposure + terrain_delta + shelter_bonus
        target_body_temp = 37.0 + max(-3.5, min(2.0, (effective_ambient - 18.0) * 0.06))
        agent.body_temperature_c = body_temp + (target_body_temp - body_temp) * min(1.0, safe_dt * 0.015)

    sleeping = getattr(agent, "sleeping", None) is True
    if sleeping:
        _update_numeric(agent, "energy", lambda value: min(100.0, value + safe_dt * (0.10 + (0.05 if shelter else 0.0))))
        _update_numeric(agent, "sleep_pressure", lambda value: max(0.0, value - safe_dt * (0.11 + (0.04 if shelter else 0.0))))
        _update_numeric(agent, "hunger", lambda value: min(100.0, value + safe_dt * 0.012))
        _update_numeric(agent, "hydration", lambda value: max(0.0, value - safe_dt * 0.018))
    else:
        energy_drain = 0.018 + (0.09 if moving is True else 0.0) + (0.02 if weather == "storm" else 0.0)
        _update_numeric(agent, "energy", lambda value: max(0.0, value - safe_dt * energy_drain))
        _update_numeric(agent, "hunger", lambda value: min(100.0, value + safe_dt * 0.018))
        _update_numeric(agent, "hydration", lambda value: max(0.0, value - safe_dt * 0.028))
        _update_numeric(agent, "sleep_pressure", lambda value: min(100.0, value + safe_dt * 0.018))

    grace = finite(getattr(agent, "grace_seconds_remaining", None), None, minimum=0.0, maximum=1_000_000_000.0)
    if grace is not None:
        grace = max(0.0, grace - safe_dt)
        agent.grace_seconds_remaining = grace
    damage = 0.0
    hydration = finite(getattr(agent, "hydration", None), None, minimum=0.0, maximum=100.0)
    hunger = finite(getattr(agent, "hunger", None), None, minimum=0.0, maximum=100.0)
    energy = finite(getattr(agent, "energy", None), None, minimum=0.0, maximum=100.0)
    body_temp = finite(getattr(agent, "body_temperature_c", None), None, minimum=0.0, maximum=100.0)
    if grace is not None and grace <= 0:
        if hydration is not None and hydration <= 4:
            damage += safe_dt * 0.20
        if hunger is not None and hunger >= 98:
            damage += safe_dt * 0.10
        if energy is not None and energy <= 1:
            damage += safe_dt * 0.07
        if body_temp is not None and (body_temp < 34.5 or body_temp > 40.0):
            damage += safe_dt * 0.16
    health = finite(getattr(agent, "health", None), None, minimum=0.0, maximum=1_000_000.0)
    pain = finite(getattr(agent, "pain", None), None, minimum=0.0, maximum=100.0)
    if damage > 0:
        if health is not None:
            health = max(0.0, health - damage)
            agent.health = health
        if pain is not None:
            agent.pain = min(100.0, pain + damage * 2)
        messages.append("Vital stress is damaging the body.")
    elif pain is not None:
        agent.pain = max(0.0, pain - safe_dt * 0.01)
    if health is not None and health <= 0:
        agent.alive = False
        agent.sleeping = False
        messages.append("The body has died.")
    return NeedTickResult(damage=damage, messages=messages)


def drive_labels(agent: AgentState) -> dict[str, str]:
    def high_bad(value: float | None) -> str:
        if value is None:
            return "unknown"
        if value >= 85:
            return "critical"
        if value >= 65:
            return "high"
        if value >= 40:
            return "medium"
        return "low"

    def low_bad(value: float | None) -> str:
        if value is None:
            return "unknown"
        if value <= 10:
            return "critical"
        if value <= 30:
            return "low"
        if value <= 60:
            return "medium"
        return "good"

    body_temp = finite(getattr(agent, "body_temperature_c", None), None, minimum=0.0, maximum=100.0)
    temp = "unknown"
    if body_temp is not None:
        temp = "comfortable"
        if body_temp < 35.0:
            temp = "dangerously cold"
        elif body_temp < 36.2:
            temp = "cold"
        elif body_temp > 39.2:
            temp = "dangerously hot"
        elif body_temp > 37.8:
            temp = "hot"
    return {
        "health": low_bad(finite(getattr(agent, "health", None), None)),
        "energy": low_bad(finite(getattr(agent, "energy", None), None)),
        "hunger": high_bad(finite(getattr(agent, "hunger", None), None)),
        "hydration": low_bad(finite(getattr(agent, "hydration", None), None)),
        "sleep_pressure": high_bad(finite(getattr(agent, "sleep_pressure", None), None)),
        "temperature": temp,
        "pain": high_bad(finite(getattr(agent, "pain", None), None)),
    }
