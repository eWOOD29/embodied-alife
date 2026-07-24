from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.diagnostics import build_diagnostic_bundle
from app.llm.client import BrainResult
from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision
from app.main import create_app
from app.memory.vault import MemoryVault
from app.serialization import json_safe, strict_json_dumps
from app.simulation.actions import ActionController, ActionResult, project_view_result_for_recent_outcome
from app.simulation.agent import AgentState
from app.simulation.cognition import MapMarker, NoteRecord, Provenance, TaskRecord
from app.simulation.engine import SimulationEngine
from app.simulation.integrity import attach_key, seal_deterministic_starters, seal_knowledge, seal_record
from app.simulation.perception import build_perception
from app.simulation.world import Terrain, WorldState
from app.storage.database import Database

TEST_KEY = b"post5-test-integrity-key-material".ljust(32, b"!")


class HostileObject:
    def __repr__(self) -> str:
        return "<HostileObject C:\\Users\\private\\secret.txt at 0xDEADBEEF>"

    def __str__(self) -> str:
        raise AssertionError("hostile __str__ must not be called")


class CapturingBrain:
    def __init__(self) -> None:
        self.status = {"mode": "llm", "available": True}
        self.context: dict[str, Any] | None = None
        self.messages: list[dict[str, str]] | None = None

    async def check_status(self) -> dict[str, Any]:
        return self.status

    async def decide(self, context: dict[str, Any]) -> BrainResult[ActionDecision]:
        self.context = context
        self.messages = decision_messages(context)
        decision = ActionDecision(
            intent="Continue after reviewing the bounded result.",
            action="wait",
            duration_seconds=0.2,
            reason="Test the normal next-decision prompt.",
        )
        return BrainResult(decision, "llm", "ok", latency_ms=1.0, prompt_tokens=10, completion_tokens=10)

    def public_configuration(self) -> dict[str, Any]:
        return {"status": self.status, "enabled": True}


class DummyUpdater:
    def public_status(self) -> dict[str, Any]:
        return {"state": "current"}


def _prepare_agent(agent: AgentState) -> None:
    attach_key(agent, TEST_KEY)
    seal_deterministic_starters(agent, TEST_KEY)


def _seal(family: str, record: Any, agent: AgentState, *, path: str = "validated_model_response", source: str = "agent", reference: str | None = None) -> None:
    assert seal_record(
        family,
        record,
        TEST_KEY if getattr(agent, "_ari_integrity_key", None) == TEST_KEY else getattr(agent, "_ari_integrity_key", None),
        path,
        source_type=source,
        source_ref=reference or f"test:{family}",
    )


def _complete(world: WorldState, agent: AgentState, action: str) -> ActionResult:
    controller = ActionController()
    decision = ActionDecision(
        intent="Review a protected key item.",
        action=action,
        duration_seconds=0.2,
        reason="Exercise the post4 handoff.",
    )
    assert controller.start(decision, world, agent).success
    done, result, _ = controller.step(1.0, world, agent)
    assert done and result is not None and result.success
    return result


def _strict(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _seed_view_case(engine: SimulationEngine, action: str) -> tuple[str, str]:
    forbidden = f"observer_id:FORBIDDEN_{action.upper()}"
    key = getattr(engine.agent, "_ari_integrity_key", None)
    assert isinstance(key, bytes)
    if action == "view_map":
        safe = "SAFE_MAP_CELL_DESCRIPTOR"
        x, y = int(round(float(engine.agent.x))), int(round(float(engine.agent.y)))
        engine.agent.known_terrain = {f"{x},{y}": safe}
        assert seal_knowledge(engine.agent, "terrain", f"{x},{y}", safe, "validated_perception", source_ref="test:terrain")
        engine.agent.map_markers = {
            "private": MapMarker(
                "private", forbidden, "observer", {"x": x, "y": y, "extension": forbidden},
                1.0, "active", forbidden, 0.0, 0.0, provenance=Provenance("perception", forbidden, forbidden),
            )
        }
        return safe, forbidden
    if action == "view_task_journal":
        safe = "SAFE_TASK_TITLE_SENTINEL"
        record = TaskRecord(
            "safe-task", safe, "A useful recipe for checking the nearby clearing.", "ari", "active", -1000,
            1.0, 2.0, metadata={"observer_extension": forbidden}, provenance=Provenance("agent", "ari", forbidden),
        )
        engine.agent.tasks[record.task_id] = record
        assert seal_record("task", record, key, "validated_model_response", source_type="agent", source_ref="test:safe-task")
        engine.agent.tasks["private-task"] = TaskRecord(
            "private-task", forbidden, forbidden, "observer", "active", -2000, 1.0, 2.0,
            provenance=Provenance("agent", "observer", forbidden),
        )
        return safe, forbidden
    safe = "SAFE_NOTEBOOK_NOTE_PHRASE"
    record = NoteRecord(
        "safe-note", "Useful recipe note", safe, ["safe", "recipe"], "active", 1.0, 999999.0,
        provenance=Provenance("agent", "ari", forbidden),
    )
    engine.agent.notes[record.note_id] = record
    assert seal_record("note", record, key, "validated_model_response", source_type="agent", source_ref="test:safe-note")
    engine.agent.notes["private-note"] = NoteRecord(
        "private-note", forbidden, forbidden, [forbidden], "active", 1.0, 1000000.0,
        provenance=Provenance("agent", "internal", forbidden),
    )
    return safe, forbidden


@pytest.mark.parametrize("action", ["view_map", "view_task_journal", "view_notebook"])
async def test_view_result_survives_complete_persisted_next_prompt_chain(settings, action: str) -> None:
    database = Database(settings.database_path)
    engine = SimulationEngine(settings, database=database, vault=MemoryVault(settings.memory_dir), load_existing=False)
    safe, forbidden = _seed_view_case(engine, action)
    baseline_memories = list(engine.vault.list_records())

    result = _complete(engine.world, engine.agent, action)
    immediate = result.to_dict()
    immediate_text = _strict(immediate)
    assert safe in immediate_text
    assert forbidden not in immediate_text
    assert len(immediate_text) < 30000

    engine._handle_action_result(result)
    engine._persist_current()
    persisted = database.get_metadata("current_state")
    assert safe in _strict(persisted)
    database.close()

    restored_database = Database(settings.database_path)
    capturing = CapturingBrain()
    restored = SimulationEngine(
        settings,
        database=restored_database,
        vault=MemoryVault(settings.memory_dir),
        brain=capturing,
        load_existing=True,
    )
    try:
        outcomes = restored._recent_action_outcomes()
        assert outcomes[-1]["action"] == action
        assert safe in _strict(outcomes[-1]["view_result"])
        assert forbidden not in _strict(outcomes[-1])

        await restored.make_decision()
        assert capturing.messages is not None
        prompt = capturing.messages[-1]["content"]
        assert safe in prompt
        assert forbidden not in prompt
        assert len(prompt) < 30000
        assert restored.vault.list_records() == baseline_memories

        restored._handle_action_result(ActionResult(True, "wait", "completed", "A later action completed."))
        aged = restored._recent_action_outcomes()
        assert all("view_result" not in outcome for outcome in aged)
        aged_prompt = json.loads(decision_messages({
            "perception": build_perception(restored.world, restored.agent),
            "action_affordances": {},
            "active_plan": [],
            "retrieved_memories": [],
            "recent_outcomes": aged,
        })[-1]["content"])
        assert all("view_result" not in outcome for outcome in aged_prompt["recent_action_outcomes"])
    finally:
        restored_database.close()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: None, lambda: "", lambda: "not-a-number", lambda: "12.5", lambda: True,
        lambda: [], lambda: {"x": 1}, lambda: {1, 2}, lambda: b"12", lambda: math.nan,
        lambda: math.inf, lambda: -math.inf, lambda: 10**500, lambda: HostileObject(),
    ],
    ids=["none", "empty", "text", "numeric-text", "bool", "list", "mapping", "set", "bytes", "nan", "inf", "neg-inf", "extreme", "object"],
)
def test_coordinate_matrix_is_controlled_for_direct_and_loaded_state(factory: Callable[[], Any]) -> None:
    world = WorldState.generate(8401, 48)
    for loaded in (False, True):
        bad_x, bad_y = factory(), factory()
        if loaded:
            raw = AgentState(x=1.0, y=1.0).to_dict()
            raw["x"], raw["y"] = bad_x, bad_y
            agent = AgentState.from_dict(raw)
        else:
            agent = AgentState(x=1.0, y=1.0)
            agent.x, agent.y = bad_x, bad_y
        _prepare_agent(agent)
        perception = build_perception(world, agent)
        assert isinstance(perception["local_tiles"], list)
        if isinstance(bad_x, (int, float, str)) and not isinstance(bad_x, bool):
            try:
                numeric = float(bad_x)
            except (ValueError, OverflowError):
                numeric = math.nan
        else:
            numeric = math.nan
        valid = math.isfinite(numeric) and 0 <= numeric < world.size
        assert perception["underfoot"] in ({terrain.value for terrain in Terrain} if valid else {"unknown"})
        _strict(perception)
        view = _complete(world, agent, "view_map")
        _strict(view.to_dict())


@pytest.mark.parametrize("count", [10, 100, 1000])
@pytest.mark.parametrize("action", ["view_map", "view_task_journal", "view_notebook"])
def test_scale_bounds_retain_positive_sentinel_without_full_store(action: str, count: int) -> None:
    world = WorldState.generate(8402, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare_agent(agent)
    safe = f"SAFE_SCALE_{action}_{count}"
    forbidden = f"observer_id:FORBIDDEN_SCALE_{count}"
    x, y = int(agent.x), int(agent.y)
    if action == "view_map":
        agent.known_terrain = {}
        for i in range(count):
            key = f"{x + (i % 20)},{y + (i // 20)}"
            value = safe if i == 0 else f"terrain-{i}-" + "x" * 300
            agent.known_terrain[key] = value
            assert seal_knowledge(agent, "terrain", key, value, "validated_perception", source_ref=f"scale:{i}")
    elif action == "view_task_journal":
        agent.tasks = {}
        for i in range(count):
            record = TaskRecord(
                f"task-{i}", safe if i == 0 else f"task-{i}-" + "x" * 1000,
                forbidden if i == count - 1 else "useful", "ari", "active", -1000 if i == 0 else i,
                float(i), float(i), metadata={"observer": forbidden}, provenance=Provenance("agent"),
            )
            agent.tasks[record.task_id] = record
            if i != count - 1:
                _seal("task", record, agent, reference=f"scale:{i}")
    else:
        agent.notes = {}
        for i in range(count):
            record = NoteRecord(
                f"note-{i}", safe if i == 0 else f"note-{i}-" + "x" * 1000, "useful", ["safe"], "active",
                float(i), 1_000_000.0 if i == 0 else float(i), provenance=Provenance("agent"),
            )
            agent.notes[record.note_id] = record
            if i != count - 1:
                _seal("note", record, agent, reference=f"scale:{i}")
    result = _complete(world, agent, action)
    outcome = {
        "action": action,
        "success": True,
        "reason": "viewed",
        "details": "bounded",
        "view_result": project_view_result_for_recent_outcome(action, result.data),
    }
    prompt = decision_messages({
        "perception": build_perception(world, agent),
        "action_affordances": {},
        "active_plan": [],
        "retrieved_memories": [],
        "recent_outcomes": [outcome],
    })[-1]["content"]
    assert safe in prompt
    assert forbidden not in prompt
    assert len(_strict(result.to_dict())) < 30000
    assert len(prompt) < 30000


def test_creation_path_policy_retains_valid_records_and_rejects_forged_mutated_and_conflicting_records() -> None:
    world = WorldState.generate(8403, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare_agent(agent)
    honest = TaskRecord("honest", "agent recipe task", "safe", "ari", "active", 1, 0, 0, provenance=Provenance("agent"))
    _seal("task", honest, agent)
    forged = TaskRecord("forged", "PRIVATE_FORGED_TASK", "private", "ari", "active", 2, 0, 0, provenance=Provenance("agent"))
    copied = TaskRecord.from_dict(honest.to_dict())
    copied.task_id = "copied"
    mutated = TaskRecord.from_dict(honest.to_dict())
    mutated.title = "PRIVATE_MUTATED_TASK"
    agent.tasks = {"honest": honest, "forged": forged, "copied": copied, "mutated": mutated}
    text = _strict(_complete(world, agent, "view_task_journal").to_dict())
    assert "agent recipe task" in text
    assert "PRIVATE_" not in text

    safe_note = NoteRecord("safe", "recipe observation", "safe useful value", [], "active", 0, 0, provenance=Provenance("agent"))
    _seal("note", safe_note, agent)
    agent.notes = {
        "safe": safe_note,
        "bad": NoteRecord("bad", "PRIVATE_NOTE", "private", [], "active", 0, 1, provenance=Provenance("agent")),
    }
    note_text = _strict(_complete(world, agent, "view_notebook").to_dict())
    assert "recipe observation" in note_text
    assert "PRIVATE_NOTE" not in note_text

    marker = MapMarker("safe", "recipe landmark", "subjective", {"direction": "north"}, 0.5, "active", "", 0, 0, provenance=Provenance("perception"))
    _seal("marker", marker, agent, path="validated_perception", source="perception")
    agent.map_markers = {
        "safe": marker,
        "bad": MapMarker("bad", "PRIVATE_MARKER", "truth", {"x": 1, "y": 1}, 1.0, "active", "", 0, 0, provenance=Provenance("perception")),
    }
    map_text = _strict(_complete(world, agent, "view_map").to_dict())
    assert "recipe landmark" in map_text
    assert "PRIVATE_MARKER" not in map_text


def test_common_serializer_is_deterministic_bounded_and_never_uses_repr() -> None:
    cycle: dict[Any, Any] = {}
    cycle["self"] = cycle
    hostile = HostileObject()
    value = {
        7: {3, 2, 1}, "tuple": (1, 2), "bytes": b"secret-bytes", "object": hostile,
        "nan": math.nan, "inf": math.inf, "cycle": cycle,
        "deep": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "too deep"}}}}}}}}},
        "many": list(range(1000)), "text": "x" * 10000,
    }
    first = json_safe(value, max_depth=5, max_items=20, max_text=100, max_nodes=200)
    second = json_safe(value, max_depth=5, max_items=20, max_text=100, max_nodes=200)
    assert first == second
    text = strict_json_dumps(value, max_depth=5, max_items=20, max_text=100, max_nodes=200)
    json.loads(text)
    assert "0xDEADBEEF" not in text
    assert "Users" not in text
    assert "secret-bytes" not in text
    assert "NaN" not in text and "Infinity" not in text
    assert "<circular>" in text
    assert len(text) < 5000


def test_persistence_observer_api_websocket_and_diagnostics_normalize_mutated_state(engine) -> None:
    cycle: dict[str, Any] = {}
    cycle["self"] = cycle
    engine.agent.known_locations["cycle"] = cycle
    engine.agent.current_action = {"set": {3, 1, 2}, "bytes": b"private", "object": HostileObject(), "nan": math.nan}
    engine.agent.recent_events.append({"kind": "custom", "message": "safe", "data": cycle})
    engine.world.truth_notes["cycle"] = cycle  # type: ignore[assignment]
    engine.last_action_result = {"object": HostileObject(), "cycle": cycle, "path": Path("/home/private/secret")}

    serialized = engine.serialize()
    observer = engine.observer_state(include_map=True)
    _strict(serialized)
    _strict(observer)
    engine._persist_current()
    assert engine.database.get_metadata("current_state")

    app = create_app(engine.settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        state_response = client.get("/api/state")
        world_response = client.get("/api/world")
        diagnostic_response = client.get("/api/diagnostics/download")
        assert state_response.status_code == world_response.status_code == diagnostic_response.status_code == 200
        for response in (state_response, world_response, diagnostic_response):
            payload = response.json()
            _strict(payload)
            assert "0xDEADBEEF" not in response.text
            assert "/home/private/secret" not in response.text
        with client.websocket_connect("/ws") as socket:
            websocket_payload = socket.receive_json()
            _strict(websocket_payload)
            assert "0xDEADBEEF" not in _strict(websocket_payload)

    bundle = build_diagnostic_bundle(
        engine=engine,
        updater=DummyUpdater(),
        health={"status": "ok"},
        application_version="0.4.0.post5",
    )
    bundle_text = _strict(bundle)
    assert "0xDEADBEEF" not in bundle_text
    assert "/home/private/secret" not in bundle_text
