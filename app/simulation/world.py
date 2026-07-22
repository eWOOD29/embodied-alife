from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Terrain(StrEnum):
    MEADOW = "meadow"
    FOREST = "forest"
    DENSE_FOREST = "dense_forest"
    SHALLOW_WATER = "shallow_water"
    DEEP_WATER = "deep_water"
    ROCK = "rock"
    CAVE = "cave"
    BUILD_AREA = "build_area"


BLOCKING_TERRAIN = {Terrain.DENSE_FOREST, Terrain.DEEP_WATER, Terrain.ROCK}


@dataclass(slots=True)
class Resource:
    id: str
    kind: str
    x: int
    y: int
    quantity: int = 1
    max_quantity: int = 1
    portable: bool = True
    edible: bool = False
    hydration: float = 0.0
    nutrition: float = 0.0
    energy: float = 0.0
    respawn_seconds: float = 0.0
    last_harvest_time: float = -1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Shelter:
    id: str
    x: int
    y: int
    durability: float = 100.0
    quality: float = 0.5
    owner: str = "Ari"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NPC:
    id: str
    kind: str
    x: float
    y: float
    dangerous: bool = False
    passive: bool = True
    health: float = 100.0
    state: str = "wandering"
    last_move_slot: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorldState:
    seed: int
    size: int
    tiles: list[list[str]]
    resources: dict[str, Resource]
    shelters: dict[str, Shelter]
    npcs: dict[str, NPC]
    spawn: tuple[int, int]
    cave_position: tuple[int, int]
    build_area: tuple[int, int]
    sim_time: float = 0.0
    day: int = 1
    weather: str = "clear"
    ambient_temperature_c: float = 18.0
    resource_regen_clock: float = 0.0
    truth_notes: dict[str, str] = field(default_factory=dict)

    DAY_LENGTH_SECONDS = 1200.0

    @classmethod
    def generate(cls, seed: int, size: int = 128) -> "WorldState":
        rng = random.Random(seed)
        tiles = [[Terrain.MEADOW.value for _ in range(size)] for _ in range(size)]

        pond_x = int(size * 0.28 + rng.randint(-5, 5))
        pond_y = int(size * 0.62 + rng.randint(-5, 5))
        pond_rx = max(7, size // 13)
        pond_ry = max(5, size // 17)
        for y in range(size):
            for x in range(size):
                d = ((x - pond_x) / pond_rx) ** 2 + ((y - pond_y) / pond_ry) ** 2
                if d < 0.55:
                    tiles[y][x] = Terrain.DEEP_WATER.value
                elif d < 1.0:
                    tiles[y][x] = Terrain.SHALLOW_WATER.value

        stream_x = int(size * 0.72)
        for y in range(size):
            curve = int(4 * math.sin(y / 11.0 + (seed % 17)))
            sx = max(2, min(size - 3, stream_x + curve))
            tiles[y][sx] = Terrain.SHALLOW_WATER.value
            if y % 5 != 0:
                tiles[y][sx + 1] = Terrain.SHALLOW_WATER.value

        # Deterministic forest patches from coordinate hashing.
        for y in range(2, size - 2):
            for x in range(2, size - 2):
                if tiles[y][x] != Terrain.MEADOW.value:
                    continue
                h = cls._coord_value(seed, x // 3, y // 3, "forest")
                edge_bias = 0.10 if x < size * 0.18 or y < size * 0.22 else 0.0
                if h + edge_bias > 0.78:
                    tiles[y][x] = Terrain.DENSE_FOREST.value if h > 0.91 else Terrain.FOREST.value

        # Rocky region and cave in the north-east.
        rock_cx, rock_cy = int(size * 0.80), int(size * 0.22)
        for y in range(max(1, rock_cy - 14), min(size - 1, rock_cy + 14)):
            for x in range(max(1, rock_cx - 18), min(size - 1, rock_cx + 18)):
                dist = math.hypot((x - rock_cx) / 1.3, y - rock_cy)
                if dist < 13 and cls._coord_value(seed, x, y, "rock") > 0.42:
                    tiles[y][x] = Terrain.ROCK.value
        cave_position = cls._nearest_open(tiles, rock_cx - 8, rock_cy + 4)
        tiles[cave_position[1]][cave_position[0]] = Terrain.CAVE.value

        build_area = cls._nearest_open(tiles, int(size * 0.55), int(size * 0.55))
        bx, by = build_area
        for yy in range(max(1, by - 3), min(size - 1, by + 4)):
            for xx in range(max(1, bx - 3), min(size - 1, bx + 4)):
                if tiles[yy][xx] not in {Terrain.DEEP_WATER.value, Terrain.SHALLOW_WATER.value}:
                    tiles[yy][xx] = Terrain.BUILD_AREA.value

        spawn = cls._nearest_open(tiles, size // 2, int(size * 0.72))
        resources: dict[str, Resource] = {}
        counters: dict[str, int] = {}

        def add(kind: str, x: int, y: int, **kwargs: Any) -> None:
            counters[kind] = counters.get(kind, 0) + 1
            rid = f"{kind}_{counters[kind]:03d}"
            resources[rid] = Resource(id=rid, kind=kind, x=x, y=y, **kwargs)

        candidates = [
            (x, y)
            for y in range(2, size - 2)
            for x in range(2, size - 2)
            if tiles[y][x] in {Terrain.MEADOW.value, Terrain.FOREST.value, Terrain.BUILD_AREA.value}
        ]
        rng.shuffle(candidates)
        for x, y in candidates[: max(45, size // 2)]:
            add(
                "berry_bush",
                x,
                y,
                quantity=3,
                max_quantity=3,
                portable=False,
                edible=True,
                nutrition=22.0,
                energy=5.0,
                respawn_seconds=420.0,
            )
        offset = max(45, size // 2)
        for x, y in candidates[offset : offset + max(35, size // 3)]:
            add("branch", x, y, quantity=1, max_quantity=1, respawn_seconds=600.0)
        offset += max(35, size // 3)
        for x, y in candidates[offset : offset + max(24, size // 5)]:
            add("edible_plant", x, y, edible=True, nutrition=12.0, energy=2.0, respawn_seconds=300.0)

        rock_candidates = [
            (x, y)
            for y in range(2, size - 2)
            for x in range(2, size - 2)
            if tiles[y][x] in {Terrain.MEADOW.value, Terrain.BUILD_AREA.value}
            and math.hypot(x - rock_cx, y - rock_cy) < 30
        ]
        rng.shuffle(rock_candidates)
        for x, y in rock_candidates[:30]:
            add("stone", x, y, quantity=1, max_quantity=1, respawn_seconds=900.0)

        npcs = {
            "rabbit_01": NPC("rabbit_01", "rabbit", spawn[0] - 10, spawn[1] - 5),
            "deer_01": NPC("deer_01", "deer", size * 0.35, size * 0.35),
            "wolf_01": NPC("wolf_01", "wolf", cave_position[0] + 3, cave_position[1] + 2, dangerous=True, passive=False),
            "raven_01": NPC("raven_01", "raven", build_area[0] + 7, build_area[1] - 5),
        }
        truth_notes = {
            "cave": "The north-eastern cave is used by a dangerous wolf.",
            "western_pond": "The western pond provides drinkable water but becomes cold and exposed at night.",
            "build_area": "The central clearing has stable ground suitable for a basic shelter.",
        }
        return cls(
            seed=seed,
            size=size,
            tiles=tiles,
            resources=resources,
            shelters={},
            npcs=npcs,
            spawn=spawn,
            cave_position=cave_position,
            build_area=build_area,
            truth_notes=truth_notes,
        )

    @staticmethod
    def _coord_value(seed: int, x: int, y: int, salt: str) -> float:
        digest = hashlib.blake2b(f"{seed}:{x}:{y}:{salt}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big") / (2**64 - 1)

    @staticmethod
    def _nearest_open(tiles: list[list[str]], x: int, y: int) -> tuple[int, int]:
        size = len(tiles)
        for radius in range(size):
            for yy in range(max(1, y - radius), min(size - 1, y + radius + 1)):
                for xx in range(max(1, x - radius), min(size - 1, x + radius + 1)):
                    if tiles[yy][xx] not in {t.value for t in BLOCKING_TERRAIN} and tiles[yy][xx] != Terrain.DEEP_WATER.value:
                        return xx, yy
        return 1, 1

    def tile(self, x: int, y: int) -> Terrain:
        if not self.in_bounds(x, y):
            return Terrain.ROCK
        return Terrain(self.tiles[y][x])

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.tile(x, y) not in BLOCKING_TERRAIN

    def is_water(self, x: int, y: int) -> bool:
        return self.tile(x, y) in {Terrain.SHALLOW_WATER, Terrain.DEEP_WATER}

    def nearby_shelter(self, x: float, y: float, radius: float = 1.5) -> Shelter | None:
        return next((s for s in self.shelters.values() if s.durability > 0 and math.hypot(s.x - x, s.y - y) <= radius), None)

    def weather_for_time(self, sim_time: float) -> str:
        slot = int(sim_time // 240)
        value = self._coord_value(self.seed, slot, self.day, "weather")
        if value < 0.08:
            return "storm"
        if value < 0.24:
            return "rain"
        if value < 0.34:
            return "cloudy"
        return "clear"

    def hour(self) -> float:
        return (self.sim_time % self.DAY_LENGTH_SECONDS) / self.DAY_LENGTH_SECONDS * 24.0

    def daylight(self) -> float:
        hour = self.hour()
        return max(0.05, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.05

    def tick(self, dt: float) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        previous_weather = self.weather
        previous_day = self.day
        self.sim_time += dt
        self.day = int(self.sim_time // self.DAY_LENGTH_SECONDS) + 1
        self.weather = self.weather_for_time(self.sim_time)
        hour = self.hour()
        daily = 12.0 + 9.0 * math.sin(2 * math.pi * (hour - 8) / 24)
        weather_delta = {"clear": 2.0, "cloudy": 0.0, "rain": -3.0, "storm": -6.0}[self.weather]
        self.ambient_temperature_c = round(daily + weather_delta, 2)
        if self.weather != previous_weather:
            events.append({"kind": "weather", "message": f"Weather changed to {self.weather}.", "importance": 0.55})
        if self.day != previous_day:
            events.append({"kind": "day", "message": f"Day {self.day} began.", "importance": 0.6})

        # Resource regeneration.
        for resource in self.resources.values():
            if (
                resource.quantity < resource.max_quantity
                and resource.respawn_seconds > 0
                and resource.last_harvest_time >= 0
                and self.sim_time - resource.last_harvest_time >= resource.respawn_seconds
            ):
                resource.quantity = resource.max_quantity
                resource.last_harvest_time = -1.0

        # Deterministic NPC movement in one-second slots.
        slot = int(self.sim_time)
        for npc in self.npcs.values():
            if npc.health <= 0 or npc.last_move_slot == slot:
                continue
            npc.last_move_slot = slot
            dx, dy = self._npc_delta(npc, slot)
            nx, ny = int(round(npc.x + dx)), int(round(npc.y + dy))
            if self.is_walkable(nx, ny):
                npc.x, npc.y = float(nx), float(ny)
        return events

    def _npc_delta(self, npc: NPC, slot: int) -> tuple[int, int]:
        value = int(self._coord_value(self.seed, slot, sum(ord(c) for c in npc.id), "npc") * 9)
        directions = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]
        dx, dy = directions[value % len(directions)]
        if npc.kind == "wolf":
            # Wolf tends to remain near its cave.
            if math.hypot(npc.x - self.cave_position[0], npc.y - self.cave_position[1]) > 12:
                dx = 1 if self.cave_position[0] > npc.x else -1
                dy = 1 if self.cave_position[1] > npc.y else -1
        return dx, dy

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "size": self.size,
            "tiles": self.tiles,
            "resources": {k: v.to_dict() for k, v in self.resources.items()},
            "shelters": {k: v.to_dict() for k, v in self.shelters.items()},
            "npcs": {k: v.to_dict() for k, v in self.npcs.items()},
            "spawn": list(self.spawn),
            "cave_position": list(self.cave_position),
            "build_area": list(self.build_area),
            "sim_time": self.sim_time,
            "day": self.day,
            "weather": self.weather,
            "ambient_temperature_c": self.ambient_temperature_c,
            "resource_regen_clock": self.resource_regen_clock,
            "truth_notes": self.truth_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldState":
        return cls(
            seed=data["seed"],
            size=data["size"],
            tiles=data["tiles"],
            resources={k: Resource(**v) for k, v in data["resources"].items()},
            shelters={k: Shelter(**v) for k, v in data.get("shelters", {}).items()},
            npcs={k: NPC(**v) for k, v in data["npcs"].items()},
            spawn=tuple(data["spawn"]),
            cave_position=tuple(data["cave_position"]),
            build_area=tuple(data["build_area"]),
            sim_time=data.get("sim_time", 0.0),
            day=data.get("day", 1),
            weather=data.get("weather", "clear"),
            ambient_temperature_c=data.get("ambient_temperature_c", 18.0),
            resource_regen_clock=data.get("resource_regen_clock", 0.0),
            truth_notes=data.get("truth_notes", {}),
        )
