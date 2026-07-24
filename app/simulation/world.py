from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.serialization import finite_number, json_safe_dict
from app.simulation.safe_state import exact_dict, finite, finite_pair, integer, records, strict_text


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
        safe_x = integer(x, None, minimum=0)
        safe_y = integer(y, None, minimum=0)
        size = integer(self.size, None, minimum=1, maximum=1_000_000)
        if safe_x is None or safe_y is None or size is None or type(self.tiles) is not list or safe_y >= len(self.tiles):
            return Terrain.ROCK
        row = self.tiles[safe_y]
        if type(row) is not list or safe_x >= len(row):
            return Terrain.ROCK
        value = row[safe_x]
        try:
            return Terrain(value) if type(value) is str else Terrain.ROCK
        except ValueError:
            return Terrain.ROCK

    def in_bounds(self, x: int, y: int) -> bool:
        safe_x = integer(x, None)
        safe_y = integer(y, None)
        size = integer(self.size, None, minimum=1, maximum=1_000_000)
        return bool(safe_x is not None and safe_y is not None and size is not None and 0 <= safe_x < size and 0 <= safe_y < size)

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.tile(x, y) not in BLOCKING_TERRAIN

    def is_water(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.tile(x, y) in {Terrain.SHALLOW_WATER, Terrain.DEEP_WATER}

    def nearby_shelter(self, x: float, y: float, radius: float = 1.5) -> Shelter | None:
        position = finite_pair(x, y)
        safe_radius = finite(radius, None, minimum=0.0, maximum=1_000_000.0)
        if position is None or safe_radius is None:
            return None
        for shelter in records(self.shelters, Shelter):
            durability = finite(shelter.durability, None, minimum=0.0, maximum=1_000_000.0)
            shelter_position = finite_pair(shelter.x, shelter.y)
            if durability is None or durability <= 0 or shelter_position is None:
                continue
            if math.hypot(shelter_position[0] - position[0], shelter_position[1] - position[1]) <= safe_radius:
                return shelter
        return None

    def weather_for_time(self, sim_time: float) -> str:
        safe_time = finite(sim_time, None, minimum=0.0)
        safe_seed = integer(self.seed, None, minimum=-2_147_483_648, maximum=2_147_483_647)
        safe_day = integer(self.day, None, minimum=1, maximum=10_000_000)
        if safe_time is None or safe_seed is None or safe_day is None:
            current = strict_text(self.weather, maximum=16)
            return current if current in {"clear", "cloudy", "rain", "storm"} else "clear"
        slot = int(safe_time // 240)
        value = self._coord_value(safe_seed, slot, safe_day, "weather")
        if value < 0.08:
            return "storm"
        if value < 0.24:
            return "rain"
        if value < 0.34:
            return "cloudy"
        return "clear"

    def hour(self) -> float:
        safe_time = finite(self.sim_time, None, minimum=0.0)
        return 0.0 if safe_time is None else (safe_time % self.DAY_LENGTH_SECONDS) / self.DAY_LENGTH_SECONDS * 24.0

    def daylight(self) -> float:
        hour = self.hour()
        return max(0.05, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.05

    def tick(self, dt: float) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        safe_dt = finite(dt, None, minimum=0.0, maximum=3600.0)
        current_time = finite(self.sim_time, None, minimum=0.0)
        safe_seed = integer(self.seed, None, minimum=-2_147_483_648, maximum=2_147_483_647)
        if safe_dt is None or safe_dt <= 0 or current_time is None or safe_seed is None:
            return events

        previous_weather = self.weather if type(self.weather) is str and self.weather in {"clear", "cloudy", "rain", "storm"} else None
        previous_day = integer(self.day, None, minimum=1, maximum=10_000_000)
        next_time = current_time + safe_dt
        next_day = int(next_time // self.DAY_LENGTH_SECONDS) + 1
        self.sim_time = next_time
        self.day = next_day
        self.weather = self.weather_for_time(next_time)
        hour = self.hour()
        daily = 12.0 + 9.0 * math.sin(2 * math.pi * (hour - 8) / 24)
        weather_delta = {"clear": 2.0, "cloudy": 0.0, "rain": -3.0, "storm": -6.0}.get(self.weather, 0.0)
        self.ambient_temperature_c = round(daily + weather_delta, 2)
        if previous_weather is not None and self.weather != previous_weather:
            events.append({"kind": "weather", "message": f"Weather changed to {self.weather}.", "importance": 0.55})
        if previous_day is not None and self.day != previous_day:
            events.append({"kind": "day", "message": f"Day {self.day} began.", "importance": 0.6})

        for resource in records(self.resources, Resource):
            quantity = finite(resource.quantity, None, minimum=0.0, maximum=1_000_000.0)
            maximum = finite(resource.max_quantity, None, minimum=0.0, maximum=1_000_000.0)
            respawn = finite(resource.respawn_seconds, None, minimum=0.0, maximum=1_000_000_000.0)
            harvested = finite(resource.last_harvest_time, None, minimum=-1.0, maximum=1_000_000_000_000.0)
            if None in {quantity, maximum, respawn, harvested}:
                continue
            if quantity < maximum and respawn > 0 and harvested >= 0 and next_time - harvested >= respawn:
                resource.quantity = int(maximum) if float(maximum).is_integer() else maximum
                resource.last_harvest_time = -1.0

        slot = int(next_time)
        for npc in records(self.npcs, NPC):
            health = finite(npc.health, None, minimum=0.0, maximum=1_000_000.0)
            last_slot = integer(npc.last_move_slot, None, minimum=-1, maximum=10**15)
            position = finite_pair(npc.x, npc.y)
            npc_id = strict_text(npc.id, maximum=160)
            if health is None or health <= 0 or last_slot is None or last_slot == slot or position is None or npc_id is None:
                continue
            npc.last_move_slot = slot
            dx, dy = self._npc_delta(npc, slot)
            nx, ny = int(round(position[0] + dx)), int(round(position[1] + dy))
            if self.is_walkable(nx, ny):
                npc.x, npc.y = float(nx), float(ny)
        return events

    def _npc_delta(self, npc: NPC, slot: int) -> tuple[int, int]:
        safe_seed = integer(self.seed, None, minimum=-2_147_483_648, maximum=2_147_483_647)
        safe_slot = integer(slot, None, minimum=0, maximum=10**15)
        npc_id = strict_text(getattr(npc, "id", None), maximum=160)
        if safe_seed is None or safe_slot is None or npc_id is None:
            return 0, 0
        value = int(self._coord_value(safe_seed, safe_slot, sum(ord(c) for c in npc_id), "npc") * 9)
        directions = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]
        dx, dy = directions[value % len(directions)]
        position = finite_pair(getattr(npc, "x", None), getattr(npc, "y", None))
        cave = self.cave_position if type(self.cave_position) in {tuple, list} and len(self.cave_position) == 2 else None
        cave_pair = finite_pair(cave[0], cave[1]) if cave is not None else None
        if getattr(npc, "kind", None) == "wolf" and position is not None and cave_pair is not None:
            if math.hypot(position[0] - cave_pair[0], position[1] - cave_pair[1]) > 12:
                dx = 1 if cave_pair[0] > position[0] else -1
                dy = 1 if cave_pair[1] > position[1] else -1
        return dx, dy

    def to_dict(self) -> dict[str, Any]:
        # Project the dataclass directly so malformed nested state and circular
        # extension values are bounded before any deep-copy or raw JSON step.
        return json_safe_dict(self, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000)

    @classmethod
    def from_dict(cls, data: Any) -> "WorldState":
        if not isinstance(data, dict):
            raise ValueError("invalid_world_state")

        def integer(value: Any, *, minimum: int, maximum: int) -> int:
            number = finite_number(value)
            if number is None:
                raise ValueError("invalid_world_number")
            parsed = int(number)
            if parsed < minimum or parsed > maximum:
                raise ValueError("invalid_world_number")
            return parsed

        def number(value: Any, default: float = 0.0) -> float:
            parsed = finite_number(value, default)
            return default if parsed is None else parsed

        seed = integer(data.get("seed"), minimum=-2_147_483_648, maximum=2_147_483_647)
        size = integer(data.get("size"), minimum=32, maximum=256)
        raw_tiles = data.get("tiles")
        if not isinstance(raw_tiles, list) or len(raw_tiles) != size:
            raise ValueError("invalid_world_tiles")
        tiles: list[list[str]] = []
        allowed_terrain = {terrain.value for terrain in Terrain}
        for raw_row in raw_tiles:
            if not isinstance(raw_row, list) or len(raw_row) != size:
                raise ValueError("invalid_world_tiles")
            row: list[str] = []
            for raw_tile in raw_row:
                if not isinstance(raw_tile, str) or raw_tile not in allowed_terrain:
                    raise ValueError("invalid_world_tile")
                row.append(raw_tile)
            tiles.append(row)

        def pair(value: Any) -> tuple[int, int]:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("invalid_world_coordinate")
            x = integer(value[0], minimum=0, maximum=size - 1)
            y = integer(value[1], minimum=0, maximum=size - 1)
            return x, y

        def records(value: Any, record_type: Any) -> dict[str, Any]:
            if not isinstance(value, dict):
                return {}
            result: dict[str, Any] = {}
            for index, (raw_key, raw_value) in enumerate(value.items()):
                if index >= 10000:
                    break
                if not isinstance(raw_key, str) or not isinstance(raw_value, dict):
                    continue
                allowed = {field_info.name for field_info in __import__("dataclasses").fields(record_type)}
                payload = {key: item for key, item in raw_value.items() if key in allowed}
                payload["id"] = raw_key[:160]
                try:
                    record = record_type(**payload)
                except (TypeError, ValueError, OverflowError):
                    continue
                if record.id and record.id not in result:
                    result[record.id] = record
            return result

        truth_notes: dict[str, str] = {}
        raw_truth = data.get("truth_notes")
        if isinstance(raw_truth, dict):
            for index, (key, value) in enumerate(raw_truth.items()):
                if index >= 1000:
                    break
                if isinstance(key, str) and isinstance(value, str):
                    truth_notes[key[:160]] = value[:4000]

        weather = data.get("weather") if isinstance(data.get("weather"), str) else "clear"
        if weather not in {"clear", "cloudy", "rain", "storm"}:
            weather = "clear"
        return cls(
            seed=seed,
            size=size,
            tiles=tiles,
            resources=records(data.get("resources"), Resource),
            shelters=records(data.get("shelters"), Shelter),
            npcs=records(data.get("npcs"), NPC),
            spawn=pair(data.get("spawn")),
            cave_position=pair(data.get("cave_position")),
            build_area=pair(data.get("build_area")),
            sim_time=number(data.get("sim_time"), 0.0),
            day=max(1, integer(data.get("day", 1), minimum=1, maximum=10_000_000)),
            weather=weather,
            ambient_temperature_c=number(data.get("ambient_temperature_c"), 18.0),
            resource_regen_clock=max(0.0, number(data.get("resource_regen_clock"), 0.0)),
            truth_notes=truth_notes,
        )

