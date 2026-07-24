from __future__ import annotations

import json
import math

import pytest

from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision
from app.simulation.actions import ARI_MAP_MARKER_LIMIT, ARI_NOTE_LIMIT, ARI_TASK_LIMIT, ActionController, project_view_result_for_recent_outcome
from app.simulation.agent import AgentState
from app.simulation.cognition import MapMarker, NoteRecord, Provenance, TaskRecord
from app.simulation.integrity import attach_key, seal_knowledge, seal_record
from app.simulation.perception import build_perception
from app.simulation.world import WorldState

KEY = b"post3-compat-key".ljust(32, b"!")


def prepare(agent: AgentState) -> None:
    attach_key(agent, KEY)


def seal(family, record, agent, *, path="validated_model_response", source="agent", reference="post3"):
    assert seal_record(family, record, KEY, path, source_type=source, source_ref=reference)


def complete(world, agent, action):
    controller = ActionController()
    decision = ActionDecision(intent="post3", action=action, duration_seconds=0.2, reason="test")
    assert controller.start(decision, world, agent).success
    done, result, _ = controller.step(1.0, world, agent)
    assert done and result is not None
    return result


def recursive_text(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


@pytest.mark.parametrize("bad", [None, "", "not-number", [], (), set(), {}, {"nested": 1}, True, math.nan, math.inf, -math.inf, 10**500, -(10**500)])
def test_perception_satiety_uses_normalized_hunger_for_direct_mutation(bad):
    world = WorldState.generate(7001, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    prepare(agent)
    agent.hunger = bad
    perception = build_perception(world, agent)
    assert perception["body"]["hunger_deficit"] == 0.0
    assert perception["body"]["satiety"] == 100.0
    recursive_text(perception)


def test_task_view_exact_serialized_fields_use_allowlist_and_preserve_observer_record():
    world = WorldState.generate(7002, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    prepare(agent)
    sentinel = "FORBIDDEN_TASK_SENTINEL"
    task = TaskRecord("t1", "approved title", "approved description", "ari", "active", 4, 1, 2, metadata={"cave_truth": sentinel}, provenance=Provenance("inference", "model", sentinel))
    task.linked_marker_ids = [sentinel]
    task.linked_note_ids = [sentinel]
    task.parent_task_id = sentinel
    task.priority = {"bad": sentinel}
    task.created_at = math.nan
    task.updated_at = math.inf
    agent.tasks = {"t1": task}
    seal("task", task, agent, source="inference")
    result = complete(world, agent, "view_task_journal")
    text = recursive_text(result.to_dict())
    assert sentinel not in text
    assert "approved title" in text and "approved description" in text
    assert set(result.data["tasks"][0]) <= {"task_id", "title", "description", "status", "priority", "created_at", "updated_at", "provenance_category", "parent_task_id", "linked_marker_ids", "linked_note_ids"}
    assert agent.to_dict()["tasks"]["t1"]["metadata"]["cave_truth"] == sentinel


def test_note_view_exact_serialized_fields_use_allowlist_and_preserve_observer_record():
    world = WorldState.generate(7003, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    prepare(agent)
    sentinel = "observer_id:FORBIDDEN_NOTE_SENTINEL"
    note = NoteRecord("n1", "approved note", "approved content", ["safe", sentinel], "active", 1, 2, provenance=Provenance("agent", "model", sentinel))
    note.linked_task_ids = [sentinel]
    note.linked_marker_ids = [sentinel]
    note.created_at = math.nan
    note.updated_at = math.inf
    agent.notes = {"n1": note}
    seal("note", note, agent)
    result = complete(world, agent, "view_notebook")
    text = recursive_text(result.to_dict())
    assert sentinel not in text
    assert "approved note" in text and "approved content" in text
    assert agent.to_dict()["notes"]["n1"]["provenance"]["detail"] == sentinel


@pytest.mark.parametrize("count", [10, 100, 1000])
def test_task_and_note_immediate_results_have_fixed_record_and_text_bounds(count):
    world = WorldState.generate(7004, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]), tasks={})
    prepare(agent)
    for index in range(count):
        token = f"UNIQUE_{index}_" + "x" * 2000
        task = TaskRecord(str(index), token, token, "ari", "active", index, index, index, metadata={"truth": token}, provenance=Provenance("inference", "model"))
        note = NoteRecord(str(index), token, token, [token] * 30, "active", index, index, provenance=Provenance("agent", "model"))
        agent.tasks[str(index)] = task
        agent.notes[str(index)] = note
        seal("task", task, agent, source="inference", reference=f"task:{index}")
        seal("note", note, agent, reference=f"note:{index}")
    task_result = complete(world, agent, "view_task_journal")
    note_result = complete(world, agent, "view_notebook")
    assert task_result.data["total_tasks"] == count
    assert len(task_result.data["tasks"]) <= ARI_TASK_LIMIT
    assert note_result.data["total_notes"] == count
    assert len(note_result.data["notes"]) <= ARI_NOTE_LIMIT
    assert len(recursive_text(task_result.to_dict())) < 30000
    assert len(recursive_text(note_result.to_dict())) < 30000


def test_view_map_invalid_position_omits_dependent_cells_and_keeps_verified_relative_markers():
    world = WorldState.generate(7005, 48)
    agent = AgentState(x="bad", y=math.nan)
    prepare(agent)
    agent.known_terrain = {f"{i},{i}": "terrain-" + "t" * 300 for i in range(1000)}
    for index in range(100):
        marker = MapMarker(str(index), "marker", "unknown", {"direction": "north"}, 0.5, "active", "", 0, 0, provenance=Provenance("perception", "event"))
        agent.map_markers[str(index)] = marker
        seal("marker", marker, agent, path="validated_perception", source="perception", reference=f"marker:{index}")
    result = complete(world, agent, "view_map")
    assert result.data["position_known"] is False
    assert result.data["known_cells"] == []
    assert result.data["total_known_cells"] == 0
    assert len(result.data["markers"]) == ARI_MAP_MARKER_LIMIT
    assert result.data["total_markers"] == 100
    recursive_text(result.to_dict())


def test_action_results_remain_bounded_when_inserted_into_later_prompt():
    world = WorldState.generate(7006, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    prepare(agent)
    agent.notes = {}
    for index in range(1000):
        token = f"SENTINEL_{index}_" + "x" * 2000
        note = NoteRecord(str(index), token, token, [token], "active", index, index, provenance=Provenance("agent", "model"))
        agent.notes[str(index)] = note
        seal("note", note, agent, reference=f"note:{index}")
    result = complete(world, agent, "view_notebook")
    outcome = {
        "action": "view_notebook",
        "success": True,
        "reason": "viewed",
        "details": result.details,
        "view_result": project_view_result_for_recent_outcome("view_notebook", result.data),
    }
    prompt = decision_messages({"perception": build_perception(world, agent), "active_plan": [], "retrieved_memories": [], "recent_outcomes": [outcome]})[-1]["content"]
    assert len(prompt) < 20000
    assert "SENTINEL_999_" in prompt
    assert "SENTINEL_993_" not in prompt
