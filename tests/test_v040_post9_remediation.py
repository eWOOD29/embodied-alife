from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.diagnostics import build_diagnostic_bundle
from app.llm.fallback import FallbackBrain
from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision
from app.main import create_app
from app.memory.vault import MemoryVault
from app.simulation.actions import ActionController
from app.simulation.cognition import AWAKENING_NARRATIVE
from app.simulation.engine import SimulationEngine
from app.simulation.perception import build_perception
from app.storage.database import Database
from app.updater.manager import UpdateManager

ABSENT = object()


class HostileAwakening(dict):
    def get(self, key, default=None):
        raise RuntimeError("hostile awakening get")

    def items(self):
        raise RuntimeError("hostile awakening items")

    def __iter__(self):
        raise RuntimeError("hostile awakening iteration")

    def __bool__(self):
        raise RuntimeError("hostile awakening truthiness")

    def __repr__(self):
        raise RuntimeError("hostile awakening representation")


def _decision(action: str = "look") -> ActionDecision:
    return ActionDecision(
        intent="Exercise the production action boundary.",
        action=action,
        duration_seconds=0.2,
        reason="Post9 regression.",
    )


def _engine(settings: Settings, *, load_existing: bool) -> SimulationEngine:
    database = Database(settings.database_path)
    return SimulationEngine(
        settings,
        database=database,
        vault=MemoryVault(settings.memory_dir),
        load_existing=load_existing,
    )


def _close(engine: SimulationEngine) -> None:
    engine.database.close()


def _prepare_existing_state(
    settings: Settings,
    *,
    awakening: Any = ABSENT,
    retain_awakening_event: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    model_settings = settings.runtime_dir / "llm-settings.json"
    model_settings.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": False,
                "base_url": "http://127.0.0.1:1234/v1",
                "api_key": "***",
                "model": "synthetic-local-model",
                "context_length": 16384,
                "timeout_seconds": 60.0,
                "temperature": 0.3,
                "max_tokens": 900,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    seed = _engine(settings, load_existing=False)
    try:
        seed.world.sim_time = 321.5
        seed.agent.inventory = {"branch": 2, "stone": 1}
        seed.agent.known_locations = {"water_known": {"kind": "water", "x": 4.0, "y": 5.0}}
        seed.save_snapshot("pre-migration")
        seed._persist_current()
        state = seed.database.get_metadata("current_state")
        assert type(state) is dict and type(state.get("agent")) is dict
        if awakening is ABSENT:
            state["agent"].pop("awakening", None)
        else:
            state["agent"]["awakening"] = awakening
        if not retain_awakening_event:
            state["events"] = []
            seed.database.clear_experiment()
            seed.database.set_metadata("run_id", state["run_id"])
            seed.database.set_metadata("world_generation_id", state["world_generation_id"])
            seed.database.set_metadata("authorization_epoch_id", state["authorization_epoch_id"])
        seed.database.set_metadata("current_state", state)
        return copy.deepcopy(state), {
            "run_id": state["run_id"],
            "world_generation_id": state["world_generation_id"],
            "seed": state["world"]["seed"],
            "sim_time": state["world"]["sim_time"],
            "inventory": copy.deepcopy(state["agent"]["inventory"]),
            "known_locations": copy.deepcopy(state["agent"]["known_locations"]),
            "snapshots": copy.deepcopy(seed.database.list_snapshots()),
            "model_settings": model_settings.read_bytes(),
        }
    finally:
        _close(seed)


def _assert_no_awakening_projection(engine: SimulationEngine) -> None:
    perception = build_perception(engine.world, engine.agent)
    assert perception["awakening"] is None
    prompt = decision_messages(
        {
            "perception": perception,
            "action_affordances": {},
            "active_plan": [],
            "retrieved_memories": [],
            "recent_outcomes": [],
        }
    )[-1]["content"]
    assert AWAKENING_NARRATIVE not in prompt
    before = engine.database.get_metadata("current_state")
    FallbackBrain().decide(perception)
    assert engine.database.get_metadata("current_state") == before


def test_legacy_existing_state_with_matching_event_migrates_before_any_consumer(settings: Settings) -> None:
    original, identity = _prepare_existing_state(settings)
    original_awakening_events = [event for event in original["events"] if event.get("kind") == "awakening"]
    assert len(original_awakening_events) == 1

    restored = _engine(settings, load_existing=True)
    try:
        assert restored.run_id == identity["run_id"]
        assert restored.world_generation_id == identity["world_generation_id"]
        assert restored.agent.awakening.presented is True
        assert restored.agent.awakening.presented_at == original_awakening_events[0]["sim_time"]
        _assert_no_awakening_projection(restored)
        persisted = restored.database.get_metadata("current_state")
        assert persisted["agent"]["awakening"]["presented"] is True
        assert [event for event in persisted["events"] if event.get("kind") == "awakening"] == original_awakening_events
    finally:
        _close(restored)


def test_legacy_existing_state_without_event_fails_closed_without_fabrication(settings: Settings) -> None:
    _, identity = _prepare_existing_state(settings, retain_awakening_event=False)
    restored = _engine(settings, load_existing=True)
    try:
        assert restored.run_id == identity["run_id"]
        assert restored.world_generation_id == identity["world_generation_id"]
        assert restored.agent.awakening.presented is True
        assert restored.agent.awakening.presented_at is None
        assert not [event for event in restored.events if event.get("kind") == "awakening"]
        _assert_no_awakening_projection(restored)
    finally:
        _close(restored)


@pytest.mark.parametrize("presented", [False, True], ids=["explicit-false", "explicit-true"])
def test_explicit_current_awakening_survives_restart_snapshot_api_and_diagnostics(
    settings: Settings,
    presented: bool,
) -> None:
    _prepare_existing_state(
        settings,
        awakening={"narrative": AWAKENING_NARRATIVE, "presented": presented, "presented_at": 12.5 if presented else None},
    )
    restored = _engine(settings, load_existing=True)
    try:
        assert restored.agent.awakening.presented is presented
        assert restored.agent.awakening.presented_at == (12.5 if presented else None)
        restored.save_snapshot("explicit-current")
        restored.agent.awakening.presented = not presented
        restored.load_snapshot("explicit-current")
        assert restored.agent.awakening.presented is presented

        app = create_app(settings, engine=restored, updater=UpdateManager(settings), start_background=False)
        with TestClient(app) as client:
            state = client.get("/api/state").json()
            health = client.get("/health").json()
            diagnostics = client.get("/api/diagnostics/download").json()
        assert state["agent"]["awakening"]["presented"] is presented
        assert state["agent_perception"]["awakening"] == (AWAKENING_NARRATIVE if not presented else None)
        assert health["run_id"] == restored.run_id
        assert diagnostics["diagnostic_bundle"]["application_version"]
        assert restored.agent.awakening.presented is presented
    finally:
        _close(restored)


@pytest.mark.parametrize(
    "awakening",
    [None, 0, "invalid", [], {}, {"presented": 1}, {"presented": "false"}, HostileAwakening({"presented": False})],
    ids=["null", "zero", "scalar", "list", "empty", "integer-presented", "text-presented", "hostile-dict"],
)
def test_malformed_existing_awakening_fails_closed_and_preserves_valid_siblings(settings: Settings, awakening: Any) -> None:
    state, identity = _prepare_existing_state(settings, awakening=None)
    live = _engine(settings, load_existing=False)
    try:
        state["agent"]["awakening"] = awakening
        live._restore(state)
        assert live.run_id == identity["run_id"]
        assert live.world_generation_id == identity["world_generation_id"]
        assert live.agent.inventory == identity["inventory"]
        assert live.agent.known_locations == identity["known_locations"]
        assert live.agent.awakening.presented is True
        assert build_perception(live.world, live.agent)["awakening"] is None
    finally:
        _close(live)


def test_migration_is_persisted_once_and_reads_are_idempotent(settings: Settings) -> None:
    _prepare_existing_state(settings)
    first = _engine(settings, load_existing=True)
    try:
        migrated = first.database.get_metadata("current_state")
        assert migrated["agent"]["awakening"]["presented"] is True
    finally:
        _close(first)

    second = _engine(settings, load_existing=True)
    try:
        before = second.database.get_metadata("current_state")
        for _ in range(3):
            second.observer_state()
            build_perception(second.world, second.agent)
            build_diagnostic_bundle(
                engine=second,
                updater=UpdateManager(settings),
                health={"status": "ok"},
                application_version="0.4.0.post9",
            )
            _assert_no_awakening_projection(second)
        after = second.database.get_metadata("current_state")
        assert after == before == migrated
        assert len([event for event in after["events"] if event.get("kind") == "awakening"]) == 1
    finally:
        _close(second)


def test_legacy_snapshot_migrates_but_explicit_false_snapshot_remains_false(settings: Settings) -> None:
    engine = _engine(settings, load_existing=False)
    try:
        legacy = engine.serialize()
        legacy["agent"].pop("awakening")
        engine.database.save_snapshot("legacy", legacy)
        engine.load_snapshot("legacy")
        assert engine.agent.awakening.presented is True
        assert build_perception(engine.world, engine.agent)["awakening"] is None

        current_false = engine.serialize()
        current_false["agent"]["awakening"] = {
            "narrative": AWAKENING_NARRATIVE,
            "presented": False,
            "presented_at": None,
        }
        engine.database.save_snapshot("current-false", current_false)
        engine.load_snapshot("current-false")
        assert engine.agent.awakening.presented is False
        assert build_perception(engine.world, engine.agent)["awakening"] == AWAKENING_NARRATIVE
    finally:
        _close(engine)


def test_new_and_reset_experiments_receive_exactly_one_awakening_at_action_boundary(settings: Settings) -> None:
    engine = _engine(settings, load_existing=False)
    try:
        for phase in ("new", "reset"):
            if phase == "reset":
                old_run = engine.run_id
                old_world = engine.world_generation_id
                engine.reset(777)
                assert engine.run_id != old_run
                assert engine.world_generation_id != old_world
            assert engine.agent.awakening.presented is False
            assert build_perception(engine.world, engine.agent)["awakening"] == AWAKENING_NARRATIVE
            first = ActionController().start(_decision(), engine.world, engine.agent)
            assert first.success
            presented_at = engine.agent.awakening.presented_at
            assert engine.agent.awakening.presented is True
            assert build_perception(engine.world, engine.agent)["awakening"] is None
            second = ActionController().start(_decision(), engine.world, engine.agent)
            assert second.success
            assert engine.agent.awakening.presented_at == presented_at
            assert len([event for event in engine.events if event.get("kind") == "awakening"]) == 1
    finally:
        _close(engine)


@pytest.mark.asyncio
async def test_real_decision_chain_does_not_need_to_consume_migrated_awakening(settings: Settings) -> None:
    _prepare_existing_state(settings)
    restored = _engine(settings, load_existing=True)
    try:
        before = restored.agent.awakening.to_dict()
        assert build_perception(restored.world, restored.agent)["awakening"] is None
        await restored.make_decision()
        assert before["presented"] is True
        assert restored.agent.awakening.presented is True
        assert restored.last_decision is not None
        assert AWAKENING_NARRATIVE not in json.dumps(restored.last_decision)
    finally:
        _close(restored)


def test_migration_preserves_existing_experiment_continuity(settings: Settings) -> None:
    _, identity = _prepare_existing_state(settings)
    restored = _engine(settings, load_existing=True)
    try:
        assert restored.run_id == identity["run_id"]
        assert restored.world_generation_id == identity["world_generation_id"]
        assert restored.world.seed == identity["seed"]
        assert restored.world.sim_time == identity["sim_time"]
        assert restored.agent.inventory == identity["inventory"]
        assert restored.agent.known_locations == identity["known_locations"]
        assert restored.database.list_snapshots() == identity["snapshots"]
        assert (settings.runtime_dir / "llm-settings.json").read_bytes() == identity["model_settings"]
        assert restored.settings.llm_model == "synthetic-local-model"
        assert sorted(restored.agent.key_items) == ["blank_field_map", "field_notebook", "task_journal"]
        assert len(restored.agent.tasks) == 4
        assert restored.database.get_metadata("authorization_epoch_id") == restored.serialize()["authorization_epoch_id"]
    finally:
        _close(restored)
