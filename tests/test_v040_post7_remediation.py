from __future__ import annotations

import copy
import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.diagnostics import build_diagnostic_bundle
from app.llm.fallback import FallbackBrain
from app.llm.prompts import decision_messages
from app.main import create_app
from app.memory.vault import MemoryVault
from app.simulation.actions import ActionController
from app.simulation.affordances import build_action_affordances
from app.simulation.engine import SimulationEngine
from app.simulation.integrity import verify_knowledge
from app.simulation.perception import build_perception, ingest_perception, observe
from app.simulation.world import Terrain, WorldState
from app.storage.database import Database


class HostileList(list):
    def __iter__(self):
        raise RuntimeError("hostile __iter__")

    def __getitem__(self, item):
        raise RuntimeError("hostile __getitem__")


class HostileAppendList(HostileList):
    def append(self, item):
        raise RuntimeError("hostile append")


class HostileDict(dict):
    def items(self):
        raise RuntimeError("hostile items")

    def keys(self):
        raise RuntimeError("hostile keys")

    def values(self):
        raise RuntimeError("hostile values")

    def get(self, key, default=None):
        raise RuntimeError("hostile get")


class HostileEquality:
    def __eq__(self, other):
        raise RuntimeError("hostile __eq__")


class HostileScalar:
    def __str__(self):
        raise RuntimeError("hostile __str__")

    def __repr__(self):
        raise RuntimeError("hostile __repr__")

    def __format__(self, spec):
        raise RuntimeError("hostile __format__")

    def __bool__(self):
        raise RuntimeError("hostile __bool__")


class ArmedHash:
    def __init__(self) -> None:
        self.armed = False

    def __hash__(self) -> int:
        if self.armed:
            raise RuntimeError("hostile __hash__")
        return 7


class DummyUpdater:
    def public_status(self) -> dict[str, Any]:
        return {"status": "idle"}


def _knowledge_state(engine: SimulationEngine) -> tuple[Any, Any, Any, Any]:
    return (
        copy.deepcopy(engine.agent.explored),
        copy.deepcopy(engine.agent.known_terrain),
        copy.deepcopy(engine.agent.known_locations),
        copy.deepcopy(engine.agent.ari_knowledge_proofs),
    )


def _event(message: Any, event_id: int = 1) -> dict[str, Any]:
    return {"id": event_id, "kind": "system", "message": message, "sim_time": 0.0, "importance": 0.1, "data": {}}


def test_observer_state_uses_builtin_list_storage_without_hostile_iteration_and_preserves_siblings(engine: SimulationEngine) -> None:
    engine.events = HostileList([_event("valid sibling"), _event(HostileScalar(), 2)])
    state = engine.observer_state()
    assert any(event.get("message") == "valid sibling" for event in state["events"])
    assert json.dumps(state, allow_nan=False)


def test_api_state_and_websocket_use_strict_json_with_hostile_engine_events(engine: SimulationEngine, settings: Settings) -> None:
    engine.events = HostileList([_event("valid sibling")])
    app = create_app(settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        response = client.get("/api/state")
        assert response.status_code == 200
        assert "valid sibling" in json.dumps(response.json(), allow_nan=False)
        with client.websocket_connect("/ws") as socket:
            message = socket.receive_json()
            assert "valid sibling" in json.dumps(message, allow_nan=False)



def test_persistence_and_diagnostics_use_builtin_storage_without_hostile_container_methods(engine: SimulationEngine) -> None:
    engine.events = HostileAppendList([_event("persisted sibling")])
    engine.memory_writes = HostileList([{"title": "safe memory sibling"}])
    serialized = engine.serialize()
    assert any(event.get("message") == "persisted sibling" for event in serialized["events"])
    assert serialized["memory_writes"][0]["title"] == "safe memory sibling"
    bundle = build_diagnostic_bundle(engine=engine, updater=DummyUpdater(), health={}, application_version="0.4.0.post7")
    assert bundle["counts"]["in_memory_events"] == 1
    assert bundle["counts"]["recent_memory_writes"] == 1
    assert json.dumps(bundle, allow_nan=False)
    recorded = engine._record("system", "new safe event")
    assert recorded["message"] == "new safe event"
    assert any(event.get("message") == "persisted sibling" for event in engine.events)


def test_rest_health_and_snapshot_name_normalize_hostile_active_scalars(engine: SimulationEngine, settings: Settings) -> None:
    engine.world.sim_time = HostileScalar()  # type: ignore[assignment]
    engine.run_id = HostileScalar()  # type: ignore[assignment]
    app = create_app(settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["run_id"] is None
        response = client.post("/api/control", json={"action": "save"})
        assert response.status_code == 200
        assert response.json()["name"] == "snapshot-0"

def test_normal_prompt_uses_builtin_dict_storage_without_hostile_items_and_preserves_safe_content() -> None:
    context = {
        "perception": HostileDict({"safe_sibling": "retained", "hostile": HostileScalar()}),
        "action_affordances": {}, "active_plan": [], "retrieved_memories": [], "recent_outcomes": [],
    }
    payload = json.loads(decision_messages(context)[-1]["content"])
    assert payload["perception"]["safe_sibling"] == "retained"
    assert "hostile" not in payload["perception"] or payload["perception"]["hostile"] == "<unsupported>"


def test_first_decision_prompt_uses_builtin_list_storage_without_hostile_iteration() -> None:
    context = HostileDict({
        "perception": {"awakening": "I wake.", "available_actions": ["wait"]},
        "action_affordances": {}, "active_plan": HostileList(["safe first step"]),
        "retrieved_memories": [], "recent_outcomes": [],
    })
    payload = json.loads(decision_messages(context)[-1]["content"])
    assert payload["perception"]["awakening"] == "I wake."
    assert payload["active_plan"] == ["safe first step"]


def test_fallback_available_actions_uses_builtin_list_storage_without_hostile_slicing() -> None:
    decision = FallbackBrain().decide({"body": {}, "available_actions": HostileList(["wait", "move"])})
    assert decision.action in {"wait", "move"}


def test_scheduler_normalizes_hostile_weather_before_equality_and_continues(engine: SimulationEngine) -> None:
    engine.world.weather = HostileEquality()  # type: ignore[assignment]
    before = engine.agent.hunger
    with patch.object(WorldState, "tick", return_value=[]):
        engine._advance_substep(0.1)
    assert engine.agent.hunger != before


def test_hostile_simulation_time_survives_perception_affordance_prompt_and_fallback(engine: SimulationEngine) -> None:
    engine.world.sim_time = HostileScalar()  # type: ignore[assignment]
    perception = build_perception(engine.world, engine.agent)
    affordances = build_action_affordances(engine.world, engine.agent, perception)
    json.loads(decision_messages({
        "perception": perception, "action_affordances": affordances,
        "active_plan": [], "retrieved_memories": [], "recent_outcomes": [],
    })[-1]["content"])
    decision = FallbackBrain().decide(perception)
    assert decision.action
    result = ingest_perception(engine.world, engine.agent)
    assert result["terrain_signed"] > 0
    assert all(evidence.get("source_ref", "").startswith("perception:") for evidence in engine.agent.ari_knowledge_proofs.values())
    assert all(value.get("last_seen") is None for value in engine.agent.known_locations.values())


def test_first_perception_ingestion_creates_terrain_locations_and_valid_proofs(engine: SimulationEngine) -> None:
    result = ingest_perception(engine.world, engine.agent)
    assert result["terrain_signed"] > 0
    assert result["locations_signed"] > 0
    assert engine.agent.explored and engine.agent.known_terrain and engine.agent.known_locations
    assert all(verify_knowledge(engine.agent, "terrain", key, value) for key, value in engine.agent.known_terrain.items())
    assert all(verify_knowledge(engine.agent, "location", key, value) for key, value in engine.agent.known_locations.items())
    assert "resources" not in json.dumps(build_perception(engine.world, engine.agent).get("known_locations", []))


def test_identical_perception_same_time_is_byte_identical_and_does_not_sign(engine: SimulationEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.simulation.perception as perception_module

    calls = 0
    original = perception_module.seal_knowledge

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(perception_module, "seal_knowledge", counted)
    first = ingest_perception(engine.world, engine.agent)
    assert calls == first["terrain_signed"] + first["locations_signed"]
    before = _knowledge_state(engine)
    calls = 0
    assert ingest_perception(engine.world, engine.agent) == {"explored_added": 0, "terrain_signed": 0, "locations_signed": 0}
    assert calls == 0
    assert _knowledge_state(engine) == before


def test_identical_perception_later_time_retains_records_and_proofs_without_resigning(engine: SimulationEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.simulation.perception as perception_module

    ingest_perception(engine.world, engine.agent)
    before = _knowledge_state(engine)
    calls = 0
    original = perception_module.seal_knowledge

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(perception_module, "seal_knowledge", counted)
    engine.world.sim_time = 500.0
    assert ingest_perception(engine.world, engine.agent) == {"explored_added": 0, "terrain_signed": 0, "locations_signed": 0}
    assert calls == 0
    assert _knowledge_state(engine) == before


def test_one_materially_changed_terrain_observation_resigns_only_affected_record(engine: SimulationEngine) -> None:
    ingest_perception(engine.world, engine.agent)
    before_terrain = copy.deepcopy(engine.agent.known_terrain)
    before_locations = copy.deepcopy(engine.agent.known_locations)
    before_proofs = copy.deepcopy(engine.agent.ari_knowledge_proofs)
    x, y = int(round(engine.agent.x)), int(round(engine.agent.y))
    key = f"{x},{y}"
    replacement = Terrain.FOREST.value if engine.world.tiles[y][x] != Terrain.FOREST.value else Terrain.MEADOW.value
    engine.world.tiles[y][x] = replacement
    result = ingest_perception(engine.world, engine.agent)
    changed_proofs = {name for name, proof in engine.agent.ari_knowledge_proofs.items() if before_proofs.get(name) != proof}
    assert result["terrain_signed"] == 1
    assert changed_proofs == {f"terrain:{key}"}
    assert engine.agent.known_terrain[key] == replacement
    assert {name: value for name, value in engine.agent.known_terrain.items() if name != key} == {name: value for name, value in before_terrain.items() if name != key}
    assert engine.agent.known_locations == before_locations


def test_projection_consumers_do_not_mutate_knowledge_or_refresh_proofs(engine: SimulationEngine, settings: Settings) -> None:
    observe(engine.world, engine.agent)
    before = _knowledge_state(engine)
    perception = build_perception(engine.world, engine.agent)
    affordances = build_action_affordances(engine.world, engine.agent, perception)
    engine.observer_state()
    build_diagnostic_bundle(engine=engine, updater=DummyUpdater(), health={}, application_version="0.4.0.post7")
    decision_messages({"perception": perception, "action_affordances": affordances, "active_plan": [], "retrieved_memories": [], "recent_outcomes": []})
    decision_messages({"perception": {**perception, "awakening": "I wake."}, "action_affordances": affordances, "active_plan": [], "retrieved_memories": [], "recent_outcomes": []})
    FallbackBrain().decide(perception)
    engine.serialize()
    app = create_app(settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        assert client.get("/api/state").status_code == 200
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
    controller = ActionController()
    from app.llm.schemas import ActionDecision
    assert controller.start(ActionDecision(intent="Review", action="view_map", duration_seconds=0.2, reason="projection test"), engine.world, engine.agent).success
    completed, result, _ = controller.step(1.0, engine.world, engine.agent)
    assert completed and result is not None
    assert _knowledge_state(engine) == before


def test_snapshot_and_restart_do_not_refresh_perception_proofs(engine: SimulationEngine, settings: Settings) -> None:
    observe(engine.world, engine.agent)
    before = _knowledge_state(engine)
    engine.save_snapshot("post7-idempotence")
    after_save = _knowledge_state(engine)
    assert after_save == before
    engine.load_snapshot("post7-idempotence")
    assert _knowledge_state(engine) == before
    engine._persist_current()
    engine.database.close()
    restored_db = Database(settings.database_path)
    restored = SimulationEngine(settings, database=restored_db, vault=MemoryVault(settings.memory_dir), load_existing=True)
    try:
        assert _knowledge_state(restored) == before
        build_perception(restored.world, restored.agent)
        assert _knowledge_state(restored) == before
    finally:
        restored_db.close()


def test_reset_retains_accepted_experiment_contract_and_does_not_replay_old_perception(engine: SimulationEngine) -> None:
    observe(engine.world, engine.agent)
    old_proofs = copy.deepcopy(engine.agent.ari_knowledge_proofs)
    old_run = engine.run_id
    engine.reset(seed=54321)
    assert engine.run_id != old_run
    assert engine.agent.known_terrain == {}
    assert engine.agent.known_locations == {}
    assert engine.agent.explored == set()
    assert not any(key.startswith(("terrain:", "location:")) for key in engine.agent.ari_knowledge_proofs)
    assert engine.agent.ari_knowledge_proofs != old_proofs


def test_unsupported_bool_hash_repr_str_format_values_are_omitted_without_conversion() -> None:
    armed = ArmedHash()
    values = {armed}
    armed.armed = True
    payload = json.loads(decision_messages({
        "perception": {"hostile": HostileScalar(), "unordered": values, "safe": "retained"},
        "action_affordances": {}, "active_plan": [], "retrieved_memories": [], "recent_outcomes": [],
    })[-1]["content"])
    assert payload["perception"]["safe"] == "retained"
