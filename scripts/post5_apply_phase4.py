from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_index] + replacement + text[end_index:]


scheduler = read("app/simulation/scheduler.py")
scheduler = replace_once(
    scheduler,
    "from app.simulation.needs import update_needs\n",
    "from app.simulation.needs import update_needs\nfrom app.simulation.observer import build_observer_state\n",
    "scheduler observer import",
)
scheduler = replace_once(
    scheduler,
    '''        if existing:
            self._restore(existing)
            self._record("system", "Restored the latest local runtime state.", 0.4)
        else:
            self._new_world(settings.world_seed)
''',
    '''        restored = False
        if existing:
            try:
                self._restore(existing)
                restored = True
            except (KeyError, TypeError, ValueError, OverflowError):
                self.database.set_metadata(
                    "quarantined_malformed_current_state",
                    json_safe(existing, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000, max_source_items=250000),
                )
                self.database.set_metadata("malformed_current_state_recovery", {"action": "started_new_world", "seed": settings.world_seed})
        if restored:
            self._record("system", "Restored the latest local runtime state.", 0.4)
        else:
            self._new_world(settings.world_seed)
            if existing:
                self._record("system", "Malformed persisted state was quarantined; a new world was started without deleting the recovery copy.", 0.8)
''',
    "scheduler controlled restore",
)
scheduler = replace_once(
    scheduler,
    '''            "events": list(self.events),
            "last_action_result": self.last_action_result,
            "last_decision": self.last_decision,
            "memory_writes": list(self.memory_writes),
''',
    '''            "events": self.events,
            "last_action_result": self.last_action_result,
            "last_decision": self.last_decision,
            "memory_writes": self.memory_writes,
''',
    "scheduler bounded serialize containers",
)
scheduler = replace_once(
    scheduler,
    '''        return json_safe_dict(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000)
''',
    '''        return json_safe_dict(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000, max_source_items=250000)
''',
    "scheduler serialize source budget",
)
restore = '''    def _restore(self, state: Any) -> None:
        from app.simulation.body import ActionExecution

        if not isinstance(state, dict):
            raise ValueError("invalid_state_envelope")
        raw_world = state.get("world")
        if not isinstance(raw_world, dict):
            raise ValueError("invalid_world_state")
        self.run_id = state.get("run_id") if isinstance(state.get("run_id"), str) and state.get("run_id") else uuid.uuid4().hex
        self.world_generation_id = state.get("world_generation_id") if isinstance(state.get("world_generation_id"), str) and state.get("world_generation_id") else uuid.uuid4().hex
        self.world = WorldState.from_dict(raw_world)
        self.agent = AgentState.from_dict(state.get("agent"))
        attach_key(self.agent, self._ari_integrity_key)
        seal_deterministic_starters(self.agent, self._ari_integrity_key)
        self.controller = ActionController()
        raw_controller = state.get("controller")
        if isinstance(raw_controller, dict):
            try:
                self.controller.execution = ActionExecution.from_dict(raw_controller)
                self.agent.current_action = self.controller.execution.to_dict()
            except (KeyError, TypeError, ValueError, OverflowError):
                self.controller.execution = None
                self.agent.current_action = None
        self.paused = state.get("paused") is True
        raw_speed = state.get("speed")
        self.speed = raw_speed if isinstance(raw_speed, int) and not isinstance(raw_speed, bool) and raw_speed in {1, 10, 100} else 1
        raw_events = state.get("events")
        self.events = deque(raw_events[:600], maxlen=600) if isinstance(raw_events, (list, tuple)) else deque(maxlen=600)
        self.last_action_result = state.get("last_action_result") if isinstance(state.get("last_action_result"), dict) else None
        self.last_decision = state.get("last_decision") if isinstance(state.get("last_decision"), dict) else None
        raw_writes = state.get("memory_writes")
        self.memory_writes = deque(raw_writes[:60], maxlen=60) if isinstance(raw_writes, (list, tuple)) else deque(maxlen=60)
        self.pending_memory = state.get("pending_memory") if isinstance(state.get("pending_memory"), dict) else None
        self._decision_pending = not bool(self.controller.execution)
        self._last_persist_time = finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0
        self.database.set_metadata("run_id", self.run_id)
        self.database.set_metadata("world_generation_id", self.world_generation_id)

'''
scheduler = replace_between(scheduler, "    def _restore(", "    def _persist_current", restore, "scheduler restore")
observer = '''    def observer_state(self, *, include_map: bool = False) -> dict[str, Any]:
        return build_observer_state(self, include_map=include_map)

'''
scheduler = replace_between(scheduler, "    def observer_state(", "    async def subscribe", observer, "scheduler observer state")
write("app/simulation/scheduler.py", scheduler)


vault = read("app/memory/vault.py")
vault = replace_once(vault, "import hashlib\n", "import hashlib\nimport os\n", "vault os import")
new_list = '''    def list_records(self, limit: int | None = None, scan_limit: int = 10000) -> list[MemoryRecord]:
        maximum_scan = max(1, min(100000, int(scan_limit)))
        maximum_output = maximum_scan if limit is None else max(0, min(maximum_scan, int(limit)))
        if maximum_output == 0:
            return []
        quarantine_root = (self.root / "quarantine").resolve()
        candidate_paths: list[Path] = []
        scanned = 0
        for directory, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(name for name in dirnames if name != "quarantine")
            for filename in sorted(filenames):
                if not filename.endswith(".md"):
                    continue
                scanned += 1
                if scanned > maximum_scan:
                    break
                path = Path(directory) / filename
                resolved = path.resolve()
                if quarantine_root == resolved or quarantine_root in resolved.parents:
                    continue
                candidate_paths.append(path)
            if scanned > maximum_scan:
                break
        candidate_paths.sort(key=lambda path: path.relative_to(self.root).as_posix())
        records: deque[MemoryRecord] = deque(maxlen=maximum_output)
        for path in candidate_paths:
            try:
                record = self._parse_file(path)
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                continue
            if record:
                records.append(record)
        return list(records)

'''
vault = replace_between(vault, "    def list_records(", "    def _parse_file", new_list, "vault bounded list")
write("app/memory/vault.py", vault)


world = read("app/simulation/world.py")
world = replace_once(world, "from app.serialization import json_safe_dict\n", "from app.serialization import finite_number, json_safe_dict\n", "world finite import")
new_from = '''    @classmethod
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
                if index >= 10000 or not isinstance(raw_key, str) or not isinstance(raw_value, dict):
                    if index >= 10000:
                        break
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
'''
world = replace_between(world, "    @classmethod\n    def from_dict", "", new_from, "world loader") if False else world[:world.find("    @classmethod\n    def from_dict", world.find("    def to_dict"))] + new_from + "\n"
write("app/simulation/world.py", world)

print("post5 phase4 applied")
