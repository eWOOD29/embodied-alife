from __future__ import annotations

import copy
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.memory.vault import MemoryVault
from app.simulation.agent import AgentState
from app.simulation.engine import SimulationEngine
from app.simulation.integrity import verify_knowledge
from app.simulation.perception import build_perception, ingest_perception
from app.simulation.world import Terrain, WorldState
from app.storage.database import Database


class HostileList(list):
    def __iter__(self):
        raise RuntimeError("hostile list iteration")

    def __getitem__(self, item):
        raise RuntimeError("hostile list indexing")

    def __len__(self):
        raise RuntimeError("hostile list length")

    def __contains__(self, item):
        raise RuntimeError("hostile list containment")

    def __repr__(self):
        raise RuntimeError("hostile list representation")

    def __format__(self, spec):
        raise RuntimeError("hostile list formatting")

    def __eq__(self, other):
        raise RuntimeError("hostile list equality")

    def __lt__(self, other):
        raise RuntimeError("hostile list ordering")


class HostileTuple(tuple):
    def __iter__(self):
        raise RuntimeError("hostile tuple iteration")

    def __getitem__(self, item):
        raise RuntimeError("hostile tuple indexing")

    def __len__(self):
        raise RuntimeError("hostile tuple length")

    def __contains__(self, item):
        raise RuntimeError("hostile tuple containment")

    def __repr__(self):
        raise RuntimeError("hostile tuple representation")

    def __format__(self, spec):
        raise RuntimeError("hostile tuple formatting")

    def __eq__(self, other):
        raise RuntimeError("hostile tuple equality")

    def __lt__(self, other):
        raise RuntimeError("hostile tuple ordering")


class HostileSet(set):
    def __iter__(self):
        raise RuntimeError("hostile set iteration")

    def __len__(self):
        raise RuntimeError("hostile set length")

    def __contains__(self, item):
        raise RuntimeError("hostile set containment")

    def __repr__(self):
        raise RuntimeError("hostile set representation")

    def __format__(self, spec):
        raise RuntimeError("hostile set formatting")

    def __eq__(self, other):
        raise RuntimeError("hostile set equality")

    def __lt__(self, other):
        raise RuntimeError("hostile set ordering")


class HostileFrozenSet(frozenset):
    def __iter__(self):
        raise RuntimeError("hostile frozenset iteration")

    def __len__(self):
        raise RuntimeError("hostile frozenset length")

    def __contains__(self, item):
        raise RuntimeError("hostile frozenset containment")

    def __repr__(self):
        raise RuntimeError("hostile frozenset representation")

    def __format__(self, spec):
        raise RuntimeError("hostile frozenset formatting")

    def __eq__(self, other):
        raise RuntimeError("hostile frozenset equality")

    def __lt__(self, other):
        raise RuntimeError("hostile frozenset ordering")

    def __hash__(self):
        raise RuntimeError("hostile frozenset hashing")


class HostileText(str):
    def __new__(cls, value: str):
        instance = super().__new__(cls, value)
        instance.armed = False
        return instance

    def __str__(self):
        raise RuntimeError("hostile text conversion")

    def __repr__(self):
        raise RuntimeError("hostile text representation")

    def __format__(self, spec):
        raise RuntimeError("hostile text formatting")

    def __eq__(self, other):
        raise RuntimeError("hostile text equality")

    def __lt__(self, other):
        raise RuntimeError("hostile text ordering")

    def __hash__(self):
        if self.armed:
            raise RuntimeError("hostile text hashing")
        return str.__hash__(self)


ContainerFactory = Callable[[list[Any]], Any]


def _list_factory(values: list[Any]) -> HostileList:
    return HostileList(values)


def _tuple_factory(values: list[Any]) -> HostileTuple:
    return HostileTuple(values)


def _set_factory(values: list[Any]) -> HostileSet:
    return HostileSet(values)


def _frozenset_factory(values: list[Any]) -> HostileFrozenSet:
    return HostileFrozenSet(values)


CONTAINERS: tuple[tuple[str, ContainerFactory], ...] = (
    ("list", _list_factory),
    ("tuple", _tuple_factory),
    ("set", _set_factory),
    ("frozenset", _frozenset_factory),
)


def _native_container_values(value: Any) -> list[Any]:
    if isinstance(value, HostileList):
        return [list.__getitem__(value, index) for index in range(list.__len__(value))]
    if isinstance(value, HostileTuple):
        return [tuple.__getitem__(value, index) for index in range(tuple.__len__(value))]
    if isinstance(value, HostileSet):
        return list(set.__iter__(value))
    if isinstance(value, HostileFrozenSet):
        return list(frozenset.__iter__(value))
    raise AssertionError(type(value))


def _install_hostile_explored(agent: AgentState, factory: ContainerFactory) -> Any:
    hostile = HostileText("forged")
    source = factory(["2,2", "1,1", hostile])
    hostile.armed = True
    agent.explored = source  # type: ignore[assignment]
    return source


def _clean_meadow(world: WorldState) -> None:
    world.tiles = [[Terrain.MEADOW.value for _ in range(world.size)] for _ in range(world.size)]


def _knowledge_state(engine: SimulationEngine) -> tuple[Any, Any, Any, Any]:
    return (
        copy.deepcopy(engine.agent.explored),
        copy.deepcopy(engine.agent.known_terrain),
        copy.deepcopy(engine.agent.known_locations),
        copy.deepcopy(engine.agent.ari_knowledge_proofs),
    )


@pytest.mark.parametrize(("container_name", "factory"), CONTAINERS, ids=[name for name, _ in CONTAINERS])
def test_agent_state_to_dict_reads_hostile_explored_builtin_storage_without_overrides_and_preserves_source(
    container_name: str,
    factory: ContainerFactory,
) -> None:
    agent = AgentState()
    source = _install_hostile_explored(agent, factory)
    before_identity = id(source)
    before_values = _native_container_values(source)

    payload = agent.to_dict()

    assert payload["explored"] == ["1,1", "2,2"]
    assert payload["name"] == "Ari"
    assert id(agent.explored) == before_identity
    assert _native_container_values(source) == before_values
    assert container_name in {"list", "tuple", "set", "frozenset"}


@pytest.mark.parametrize(("container_name", "factory"), CONTAINERS, ids=[name for name, _ in CONTAINERS])
def test_engine_serialize_and_persist_hostile_explored_preserve_valid_siblings_and_restart(
    engine: SimulationEngine,
    settings: Settings,
    container_name: str,
    factory: ContainerFactory,
) -> None:
    source = _install_hostile_explored(engine.agent, factory)
    engine.agent.inventory = {"branch": 2}
    before_values = _native_container_values(source)

    serialized = engine.serialize()
    assert serialized["agent"]["explored"] == ["1,1", "2,2"]
    assert serialized["agent"]["inventory"] == {"branch": 2}
    engine._persist_current()
    assert _native_container_values(source) == before_values

    engine.database.close()
    restored_db = Database(settings.database_path)
    restored = SimulationEngine(settings, database=restored_db, vault=MemoryVault(settings.memory_dir), load_existing=True)
    try:
        assert restored.agent.explored == {"1,1", "2,2"}
        assert restored.agent.inventory == {"branch": 2}
        assert restored.serialize()["agent"]["explored"] == ["1,1", "2,2"]
    finally:
        restored_db.close()
    assert container_name in {"list", "tuple", "set", "frozenset"}


def test_oversized_hostile_unordered_explored_is_omitted_without_unbounded_scan() -> None:
    agent = AgentState()
    source = HostileSet(str(index) for index in range(10001))
    agent.explored = source  # type: ignore[assignment]
    assert agent.to_dict()["explored"] == []
    assert set.__len__(source) == 10001


def test_snapshot_and_explicit_save_api_control_hostile_explored_without_http_500(
    engine: SimulationEngine,
    settings: Settings,
) -> None:
    source = _install_hostile_explored(engine.agent, _set_factory)
    before_values = _native_container_values(source)
    saved = engine.save_snapshot("post8-hostile-explored")
    assert saved["ok"] is True
    assert engine.snapshots.load("post8-hostile-explored")["agent"]["explored"] == ["1,1", "2,2"]
    assert _native_container_values(source) == before_values

    app = create_app(settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        response = client.post("/api/control", json={"action": "save", "name": "post8-api-save"})
        assert response.status_code == 200
        assert response.json()["name"] == "post8-api-save"
    assert engine.snapshots.load("post8-api-save")["agent"]["explored"] == ["1,1", "2,2"]
    assert _native_container_values(source) == before_values


@pytest.mark.asyncio
async def test_autosave_and_stop_time_persistence_hostile_explored_are_controlled(
    engine: SimulationEngine,
    settings: Settings,
) -> None:
    _install_hostile_explored(engine.agent, _frozenset_factory)
    engine._last_persist_time = 0.0
    engine.world.sim_time = 31.0
    await engine.advance(0.1, allow_decision=False)
    persisted = engine.database.get_metadata("current_state")
    assert persisted["agent"]["explored"] == ["1,1", "2,2"]

    await engine.stop()
    restored_db = Database(settings.database_path)
    restored = SimulationEngine(settings, database=restored_db, vault=MemoryVault(settings.memory_dir), load_existing=True)
    try:
        assert restored.agent.explored == {"1,1", "2,2"}
    finally:
        restored_db.close()


def test_hostile_root_tile_container_creates_no_signed_terrain_in_direct_ingestion_or_decision(
    engine: SimulationEngine,
) -> None:
    _clean_meadow(engine.world)
    engine.world.tiles = HostileList(engine.world.tiles)
    source = engine.world.tiles
    before_rows = list.__len__(source)

    assert ingest_perception(engine.world, engine.agent, radius=2) == {
        "explored_added": 0,
        "terrain_signed": 0,
        "locations_signed": 0,
    }
    assert engine.agent.known_terrain == {}
    assert not any(key.startswith("terrain:") for key in engine.agent.ari_knowledge_proofs)
    assert build_perception(engine.world, engine.agent, radius=2)["local_tiles"] == []

    assert list.__len__(source) == before_rows


@pytest.mark.asyncio
async def test_make_decision_hostile_root_tile_container_does_not_create_false_authority(
    engine: SimulationEngine,
) -> None:
    _clean_meadow(engine.world)
    engine.world.tiles = HostileList(engine.world.tiles)
    await engine.make_decision()
    assert engine.agent.known_terrain == {}
    assert engine.agent.known_locations == {}
    assert not any(key.startswith(("terrain:", "location:")) for key in engine.agent.ari_knowledge_proofs)


def test_hostile_row_is_omitted_while_valid_neighboring_rows_survive_without_rock_authority(
    engine: SimulationEngine,
) -> None:
    _clean_meadow(engine.world)
    ax, ay = int(round(engine.agent.x)), int(round(engine.agent.y))
    bad_y = ay + 1
    original_row = engine.world.tiles[bad_y]
    hostile_row = HostileList(original_row)
    engine.world.tiles[bad_y] = hostile_row

    result = ingest_perception(engine.world, engine.agent, radius=2)
    assert result["terrain_signed"] > 0
    assert any(key.endswith(f",{ay}") for key in engine.agent.known_terrain)
    assert not any(key.endswith(f",{bad_y}") for key in engine.agent.known_terrain)
    assert set(engine.agent.known_terrain.values()) == {Terrain.MEADOW.value}
    assert all(verify_knowledge(engine.agent, "terrain", key, value) for key, value in engine.agent.known_terrain.items())
    assert list.__len__(hostile_row) == len(original_row)


def test_malformed_scalar_is_omitted_while_valid_neighbor_cells_survive_without_plausible_replacement(
    engine: SimulationEngine,
) -> None:
    _clean_meadow(engine.world)
    ax, ay = int(round(engine.agent.x)), int(round(engine.agent.y))
    engine.world.tiles[ay][ax] = object()  # type: ignore[list-item]
    invalid_key = f"{ax},{ay}"

    result = ingest_perception(engine.world, engine.agent, radius=2)
    assert result["terrain_signed"] > 0
    assert invalid_key not in engine.agent.known_terrain
    assert f"{ax + 1},{ay}" in engine.agent.known_terrain
    assert set(engine.agent.known_terrain.values()) == {Terrain.MEADOW.value}
    assert not verify_knowledge(engine.agent, "terrain", invalid_key, Terrain.ROCK.value)
    assert type(engine.world.tiles[ay][ax]) is object


def test_unexpected_tile_failure_discards_whole_observation_batch_without_partial_commit(
    engine: SimulationEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_meadow(engine.world)
    ax, ay = int(round(engine.agent.x)), int(round(engine.agent.y))
    original = WorldState.tile

    def failing_tile(world: WorldState, x: int, y: int):
        if x == ax and y == ay:
            raise RuntimeError("unexpected observation failure")
        return original(world, x, y)

    monkeypatch.setattr(WorldState, "tile", failing_tile)
    before = _knowledge_state(engine)
    result = ingest_perception(engine.world, engine.agent, radius=2)
    assert result == {"explored_added": 0, "terrain_signed": 0, "locations_signed": 0}
    assert _knowledge_state(engine) == before


def test_valid_terrain_remains_idempotent_and_one_real_change_updates_only_affected_proof(
    engine: SimulationEngine,
) -> None:
    _clean_meadow(engine.world)
    first = ingest_perception(engine.world, engine.agent, radius=2)
    assert first["terrain_signed"] > 0
    before = _knowledge_state(engine)
    assert ingest_perception(engine.world, engine.agent, radius=2) == {
        "explored_added": 0,
        "terrain_signed": 0,
        "locations_signed": 0,
    }
    assert _knowledge_state(engine) == before

    ax, ay = int(round(engine.agent.x)), int(round(engine.agent.y))
    key = f"{ax},{ay}"
    before_proofs = copy.deepcopy(engine.agent.ari_knowledge_proofs)
    engine.world.tiles[ay][ax] = Terrain.FOREST.value
    changed = ingest_perception(engine.world, engine.agent, radius=2)
    assert changed["terrain_signed"] == 1
    changed_proofs = {name for name, proof in engine.agent.ari_knowledge_proofs.items() if before_proofs.get(name) != proof}
    assert changed_proofs == {f"terrain:{key}"}
    assert engine.agent.known_terrain[key] == Terrain.FOREST.value


def test_valid_terrain_proofs_survive_restart_snapshot_and_reset_rotates_authority(
    engine: SimulationEngine,
    settings: Settings,
) -> None:
    _clean_meadow(engine.world)
    ingest_perception(engine.world, engine.agent, radius=2)
    before = _knowledge_state(engine)
    engine.save_snapshot("post8-valid-terrain")
    engine.load_snapshot("post8-valid-terrain")
    assert _knowledge_state(engine) == before
    engine._persist_current()
    engine.database.close()

    restored_db = Database(settings.database_path)
    restored = SimulationEngine(settings, database=restored_db, vault=MemoryVault(settings.memory_dir), load_existing=True)
    try:
        assert _knowledge_state(restored) == before
        old_run = restored.run_id
        old_proofs = copy.deepcopy(restored.agent.ari_knowledge_proofs)
        restored.reset(seed=98765)
        assert restored.run_id != old_run
        assert restored.agent.known_terrain == {}
        assert not any(key.startswith("terrain:") for key in restored.agent.ari_knowledge_proofs)
        assert restored.agent.ari_knowledge_proofs != old_proofs
        first_new = ingest_perception(restored.world, restored.agent, radius=2)
        assert first_new["terrain_signed"] > 0
    finally:
        restored_db.close()
