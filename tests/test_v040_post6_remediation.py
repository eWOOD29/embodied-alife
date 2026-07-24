from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm.fallback import FallbackBrain
from app.llm.prompts import decision_messages
from app.main import create_app
from app.memory.vault import MemoryVault
from app.simulation.actions import ActionController, ActionResult
from app.simulation.agent import AgentState
from app.simulation.cognition import MapMarker, NoteRecord, Provenance, TaskRecord
from app.simulation.affordances import build_action_affordances
from app.simulation.engine import SimulationEngine
from app.simulation.perception import build_perception
from app.simulation.integrity import (
    attach_key,
    current_epoch_id,
    seal_record,
    sign_payload,
    verify_event,
    verify_payload,
    verify_record,
)
from app.simulation.world import NPC, Resource, Shelter
from app.storage.database import Database

TEST_KEY = b"post6-exploit-regression-key".ljust(32, b"!")


class HostileMapping(dict):
    def items(self):
        raise RuntimeError("items must not be called")

    def keys(self):
        raise RuntimeError("keys must not be called")

    def values(self):
        raise RuntimeError("values must not be called")

    def get(self, key, default=None):
        raise RuntimeError("get must not be called")


class HostileIterator:
    def __iter__(self):
        raise RuntimeError("iterator must not be called")


class HostileObject:
    def __repr__(self) -> str:
        raise RuntimeError("repr must not be called")

    def __str__(self) -> str:
        raise RuntimeError("str must not be called")


def _agent(*, epoch: str = "post6-test-epoch", run: str = "post6-test-run", world: str = "post6-test-world") -> AgentState:
    agent = AgentState(x=10.0, y=10.0)
    attach_key(agent, TEST_KEY, epoch_id=epoch, run_id=run, world_generation_id=world)
    return agent


def _seal(family: str, record: Any, agent: AgentState, *, source: str = "agent", path: str = "validated_model_response") -> None:
    assert seal_record(
        family,
        record,
        TEST_KEY,
        path,
        source_type=source,
        source_ref=f"post6:{family}",
        authority=agent,
    )


def _complete_view(engine: SimulationEngine, action: str) -> ActionResult:
    controller = ActionController()
    from app.llm.schemas import ActionDecision

    decision = ActionDecision(intent="Review", action=action, duration_seconds=0.2, reason="Post6 regression")
    assert controller.start(decision, engine.world, engine.agent).success
    completed, result, _ = controller.step(1.0, engine.world, engine.agent)
    assert completed and result is not None
    return result


def test_post5_after_64_marker_location_mutation_invalidates_and_never_reaches_ari(engine: SimulationEngine) -> None:
    location = {f"ignored-{index}": index for index in range(65)}
    location.update({"x": 12.0, "y": 13.0})
    marker = MapMarker(
        "tail-marker",
        "Tail marker",
        "subjective",
        location,
        0.9,
        "active",
        "",
        1.0,
        1.0,
        provenance=Provenance("perception"),
    )
    assert seal_record(
        "marker",
        marker,
        engine._ari_integrity_key,
        "validated_perception",
        source_type="perception",
        source_ref="post6:tail-marker",
        authority=engine.agent,
    )
    assert verify_record("marker", marker, engine.agent)
    marker.believed_location["x"] = 1010.0
    marker.believed_location["y"] = 1010.0
    assert not verify_record("marker", marker, engine.agent)
    engine.agent.map_markers = {marker.marker_id: marker}
    result = _complete_view(engine, "view_map")
    encoded = json.dumps(result.data, sort_keys=True)
    assert "Tail marker" not in encoded
    assert "1010" not in encoded


def test_post5_after_2000_note_mutation_invalidates() -> None:
    agent = _agent()
    original = "A" * 2500 + "ORIGINAL_TAIL"
    note = NoteRecord("long-note", "Long note", original, [], "active", 1.0, 1.0, provenance=Provenance("agent"))
    _seal("note", note, agent)
    assert verify_record("note", note, agent)
    note.content = note.content[:2200] + "FORGED_TAIL" + note.content[2211:]
    assert not verify_record("note", note, agent)


def test_post5_linked_id_after_64_mutation_invalidates() -> None:
    agent = _agent()
    links = [f"note-{index:03d}" for index in range(80)]
    task = TaskRecord(
        "linked-task",
        "Linked task",
        "Complete links",
        "ari",
        "active",
        1,
        1.0,
        2.0,
        linked_note_ids=links,
        provenance=Provenance("agent"),
    )
    _seal("task", task, agent)
    assert verify_record("task", task, agent)
    task.linked_note_ids[65] = "forged-note-065"
    assert not verify_record("task", task, agent)


def test_record_proof_is_bound_to_id_family_and_all_ari_fields() -> None:
    agent = _agent()
    note = NoteRecord("record-a", "Title", "Content", ["tag"], "active", 1.0, 2.0, provenance=Provenance("agent"))
    _seal("note", note, agent)
    assert verify_record("note", note, agent)

    copied_id = NoteRecord.from_dict(note.to_dict())
    copied_id.note_id = "record-b"
    assert not verify_record("note", copied_id, agent)

    task = TaskRecord("record-a", "Title", "Content", "ari", "active", 1, 1.0, 2.0, provenance=Provenance("agent"))
    task.provenance.proof = note.provenance.proof
    task.provenance.proof_version = note.provenance.proof_version
    task.provenance.creation_path = note.provenance.creation_path
    task.provenance.source_id = note.provenance.source_id
    assert not verify_record("task", task, agent)

    for field, value in {
        "title": "Changed title",
        "content": "Changed content",
        "status": "archived",
        "created_at": 9.0,
        "updated_at": 10.0,
        "tags": ["changed"],
        "linked_task_ids": ["changed-task"],
        "linked_marker_ids": ["changed-marker"],
    }.items():
        mutated = NoteRecord.from_dict(note.to_dict())
        setattr(mutated, field, value)
        assert not verify_record("note", mutated, agent), field



def test_malformed_builtin_numeric_inputs_are_bound_exactly_when_legacy_projection_normalizes() -> None:
    agent = _agent()
    task = TaskRecord("legacy-malformed", "Legacy", "Malformed field", "ari", "active", 1, 1.0, 1.0, provenance=Provenance("agent"))
    task.priority = {"bad": "original"}
    _seal("task", task, agent)
    assert verify_record("task", task, agent)
    task.priority = {"bad": "changed"}
    assert not verify_record("task", task, agent)

    note = NoteRecord("legacy-time", "Legacy", "Malformed time", [], "active", float("nan"), float("inf"), provenance=Provenance("agent"))
    _seal("note", note, agent)
    assert verify_record("note", note, agent)
    note.created_at = float("inf")
    assert not verify_record("note", note, agent)

def test_same_experiment_restart_succeeds_but_reset_replay_fails(settings) -> None:
    first_db = Database(settings.database_path)
    first = SimulationEngine(settings, database=first_db, vault=MemoryVault(settings.memory_dir), load_existing=False)
    note = NoteRecord("restart-note", "Restart", "same experiment", [], "active", 1.0, 1.0, provenance=Provenance("agent"))
    assert seal_record(
        "note",
        note,
        first._ari_integrity_key,
        "validated_model_response",
        source_type="agent",
        source_ref="post6:restart",
        authority=first.agent,
    )
    first.agent.notes[note.note_id] = note
    old_note = NoteRecord.from_dict(note.to_dict())
    old_epoch = current_epoch_id(settings.runtime_dir)
    first._persist_current()
    first_db.close()

    second_db = Database(settings.database_path)
    second = SimulationEngine(settings, database=second_db, vault=MemoryVault(settings.memory_dir), load_existing=True)
    try:
        assert current_epoch_id(settings.runtime_dir) == old_epoch
        assert verify_record("note", second.agent.notes[note.note_id], second.agent)
        second.reset(seed=777)
        assert current_epoch_id(settings.runtime_dir) != old_epoch
        second.agent.notes[old_note.note_id] = old_note
        assert not verify_record("note", old_note, second.agent)
        assert old_note.note_id not in {entry.get("note_id") for entry in _complete_view(second, "view_notebook").data["notes"]}
    finally:
        second_db.close()


def test_snapshot_same_experiment_succeeds_and_cross_epoch_snapshot_fails(engine: SimulationEngine) -> None:
    note = NoteRecord("snapshot-note", "Snapshot", "same epoch", [], "active", 1.0, 1.0, provenance=Provenance("agent"))
    assert seal_record(
        "note",
        note,
        engine._ari_integrity_key,
        "validated_model_response",
        source_type="agent",
        source_ref="post6:snapshot",
        authority=engine.agent,
    )
    engine.agent.notes[note.note_id] = note
    engine.save_snapshot("post6-same")
    engine.agent.notes.clear()
    engine.load_snapshot("post6-same")
    assert verify_record("note", engine.agent.notes[note.note_id], engine.agent)
    old_state = copy.deepcopy(engine.snapshots.load("post6-same"))
    engine.reset(seed=888)
    with pytest.raises(ValueError, match="authorization_epoch_mismatch"):
        engine._restore(old_state)


def test_recent_outcome_is_bound_to_exact_event_identity_and_complete_result(engine: SimulationEngine) -> None:
    result = ActionResult(
        True,
        "view_notebook",
        "viewed",
        "safe",
        {"notes": [{"note_id": "n", "title": "Safe", "content": "complete", "status": "active"}], "total_notes": 1},
    )
    engine.current_decision_event_id = 17
    engine.last_decision = {"action": "view_notebook", "target_id": None}
    engine._handle_action_result(result)
    event = next(item for item in reversed(engine.events) if item.get("kind") == "action_result")
    evidence = event["data"]["_ari_integrity"]
    assert verify_event(engine.agent, "recent_outcome", event, evidence)

    mutations = [
        ("id", event["id"] + 1),
        ("run_id", "other-run"),
        ("world_generation_id", "other-world"),
        ("authorization_epoch_id", "0" * 32),
        ("kind", "other-event"),
        ("sim_time", event["sim_time"] + 1),
        ("message", "changed message"),
    ]
    for field, value in mutations:
        forged = copy.deepcopy(event)
        forged[field] = value
        assert not verify_event(engine.agent, "recent_outcome", forged, forged["data"]["_ari_integrity"]), field

    for path, value in [
        (("action",), "view_map"),
        (("success",), False),
        (("details",), "changed"),
        (("data", "notes", 0, "content"), "forged"),
        (("decision_event_id",), 999),
    ]:
        forged = copy.deepcopy(event)
        target: Any = forged["data"]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert not verify_event(engine.agent, "recent_outcome", forged, forged["data"]["_ari_integrity"]), path

    copied = copy.deepcopy(event)
    copied["id"] += 100
    copied["data"] = copy.deepcopy(event["data"])
    assert not verify_event(engine.agent, "recent_outcome", copied, copied["data"]["_ari_integrity"])


def test_verification_boundary_rejects_hostile_and_malformed_inputs_without_real_view_crash(engine: SimulationEngine) -> None:
    assert not verify_record("task", HostileMapping(), engine.agent)
    assert sign_payload(engine.agent, "hostile", HostileMapping(), "validated_action_event", source_ref="hostile") is None
    assert sign_payload(engine.agent, "hostile", HostileIterator(), "validated_action_event", source_ref="hostile") is None
    assert sign_payload(engine.agent, "hostile", HostileObject(), "validated_action_event", source_ref="hostile") is None
    cyclic: list[Any] = []
    cyclic.append(cyclic)
    assert sign_payload(engine.agent, "hostile", cyclic, "validated_action_event", source_ref="hostile") is None

    for evidence in [None, "bad", b"bad", {}, {"proof": "z" * 64}, {"proof_version": True}]:
        assert not verify_payload(engine.agent, "recent_outcome", {}, evidence)

    engine.agent.tasks = HostileMapping()
    result = _complete_view(engine, "view_task_journal")
    assert result.success
    assert result.data["tasks"] == []
    observer = engine.observer_state()
    assert isinstance(observer, dict)


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (None, "sim_time"),
        ("not-a-number", "sim_time"),
        (float("nan"), "sim_time"),
        (float("inf"), "sim_time"),
        (HostileMapping(), "resources"),
        (HostileMapping(), "npcs"),
        (HostileMapping(), "shelters"),
    ],
)
def test_malformed_active_world_containers_and_time_do_not_crash(engine: SimulationEngine, mutation: Any, field: str) -> None:
    setattr(engine.world, field, mutation)
    engine._advance_substep(1.0)
    engine.observer_state()
    engine.serialize()


def test_malformed_active_resource_npc_and_shelter_records_do_not_crash(engine: SimulationEngine) -> None:
    resource = next(iter(engine.world.resources.values()))
    npc = next(iter(engine.world.npcs.values()))
    engine.world.shelters["bad-shelter"] = Shelter("bad-shelter", 1, 1)
    shelter = engine.world.shelters["bad-shelter"]

    malformed_values = [None, "", "bad", True, [], (), set(), b"bytes", {}, HostileObject(), float("nan"), float("inf"), -1e300, 1e300]
    for value in malformed_values:
        resource.quantity = value
        resource.x = value
        resource.y = value
        npc.health = value
        npc.x = value
        npc.y = value
        shelter.durability = value
        shelter.x = value
        shelter.y = value
        engine._advance_substep(1.0)
        engine.observer_state()
        engine.serialize()



def test_action_validation_and_execution_fail_closed_on_malformed_active_state(engine: SimulationEngine) -> None:
    from app.llm.schemas import ActionDecision
    from app.simulation.body import ActionExecution

    controller = ActionController()
    engine.world.resources = HostileMapping()
    engine.agent.inventory = HostileMapping()
    for decision in [
        ActionDecision(intent="test", action="pick_up", target_id="missing", duration_seconds=0.2, reason="test"),
        ActionDecision(intent="test", action="build", duration_seconds=0.2, reason="test"),
        ActionDecision(intent="test", action="drop", target_id="branch", duration_seconds=0.2, reason="test"),
    ]:
        result = controller.start(decision, engine.world, engine.agent)
        assert not result.success

    controller.execution = ActionExecution("wait", None, 1.0, 1.0, [], None, 0.0, {})
    controller.execution.remaining = HostileObject()
    completed, result, moving = controller.step(1.0, engine.world, engine.agent)
    assert completed and result is not None and not result.success and result.reason == "malformed_execution"
    assert moving is False

    engine.agent.energy = HostileObject()
    engine.agent.health = HostileObject()
    engine.agent.pain = HostileObject()
    controller.execution = ActionExecution("move", None, 1.0, 1.0, [(int(engine.agent.x), int(engine.agent.y))], None, 0.0, {})
    completed, result, _ = controller.step(1.0, engine.world, engine.agent)
    assert completed

def test_positive_authorized_task_note_marker_and_event_continuity(engine: SimulationEngine) -> None:
    task = TaskRecord("positive-task", "Useful task", "Do something useful", "ari", "active", 1, 1.0, 1.0, provenance=Provenance("agent"))
    note = NoteRecord("positive-note", "Useful note", "Useful content", ["useful"], "active", 1.0, 1.0, provenance=Provenance("agent"))
    marker = MapMarker("positive-marker", "Useful marker", "subjective", {"x": engine.agent.x + 2, "y": engine.agent.y}, 0.8, "active", "", 1.0, 1.0, provenance=Provenance("perception"))
    for family, record, source, path in [
        ("task", task, "agent", "validated_model_response"),
        ("note", note, "agent", "validated_model_response"),
        ("marker", marker, "perception", "validated_perception"),
    ]:
        assert seal_record(family, record, engine._ari_integrity_key, path, source_type=source, source_ref=f"positive:{family}", authority=engine.agent)
        assert verify_record(family, record, engine.agent)
    engine.agent.tasks[task.task_id] = task
    engine.agent.notes[note.note_id] = note
    engine.agent.map_markers[marker.marker_id] = marker
    assert "Useful task" in json.dumps(_complete_view(engine, "view_task_journal").data)
    assert "Useful note" in json.dumps(_complete_view(engine, "view_notebook").data)
    assert "Useful marker" in json.dumps(_complete_view(engine, "view_map").data)

    engine._handle_action_result(ActionResult(True, "view_notebook", "viewed", "useful", _complete_view(engine, "view_notebook").data))
    outcomes = engine._recent_action_outcomes()
    assert outcomes and outcomes[-1]["view_result"]["notes"][0]["title"] == "Useful note"
    observer = engine.observer_state()
    assert "positive-note" in observer["agent"]["notes"]


@pytest.mark.asyncio
async def test_malformed_active_state_survives_scheduler_prompt_fallback_persistence_rest_and_websocket(engine: SimulationEngine, settings) -> None:
    engine.world.resources = HostileMapping()
    engine.world.npcs = HostileMapping()
    engine.world.shelters = HostileMapping()
    engine.world.sim_time = "malformed-time"
    engine.agent.inventory = HostileMapping()

    await engine.advance(1.0, allow_decision=False)
    perception = build_perception(engine.world, engine.agent)
    affordances = build_action_affordances(engine.world, engine.agent, perception)
    prompt = decision_messages({
        "perception": perception,
        "action_affordances": affordances,
        "active_plan": engine.agent.active_plan,
        "retrieved_memories": [],
        "recent_outcomes": [],
    })[-1]["content"]
    json.loads(prompt)
    fallback = FallbackBrain().decide(perception)
    json.dumps(fallback.model_dump(), allow_nan=False)
    engine._persist_current()
    assert type(engine.database.get_metadata("current_state")) is dict

    app = create_app(settings, engine=engine, start_background=False)
    with TestClient(app) as client:
        state_response = client.get("/api/state")
        world_response = client.get("/api/world")
        diagnostics_response = client.get("/api/diagnostics/download")
        assert state_response.status_code == 200
        assert world_response.status_code == 200
        assert diagnostics_response.status_code == 200
        json.dumps(state_response.json(), allow_nan=False)
        json.dumps(world_response.json(), allow_nan=False)
        with client.websocket_connect("/ws") as socket:
            message = socket.receive_json()
            json.dumps(message, allow_nan=False)
