from __future__ import annotations

import json

from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision
from app.simulation.actions import ActionController
from app.simulation.agent import AgentState
from app.simulation.cognition import AWAKENING_NARRATIVE, BeliefRecord, BeliefStatus, EpisodeRecord, MapMarker, NoteRecord, Provenance
from app.simulation.perception import build_perception
from app.simulation.world import WorldState
from app.storage.database import Database


def _decision(action: str, *, target_id: str | None = None) -> ActionDecision:
    return ActionDecision(intent=f"Exercise {action}.", action=action, target_id=target_id, duration_seconds=0.2, reason="Acceptance test.")


def _complete(controller: ActionController, world: WorldState, agent: AgentState, action: str):
    assert controller.start(_decision(action), world, agent).success
    completed, result, _ = controller.step(1.0, world, agent)
    assert completed and result is not None
    return result


def _cognition(agent: AgentState) -> dict:
    state = agent.to_dict()
    return {key: state[key] for key in ("key_items", "tasks", "notes", "map_markers", "beliefs", "short_term_episodes", "awakening", "cognition_schema_version")}


def test_fresh_agent_has_starter_key_items_and_tasks_without_capacity_cost() -> None:
    agent = AgentState()
    assert sorted(agent.key_items) == ["blank_field_map", "field_notebook", "task_journal"]
    assert agent.inventory_used == 0
    assert len(agent.tasks) == 4 and len(set(agent.tasks)) == 4
    assert all(task.status == "proposed" for task in agent.tasks.values())
    assert agent.add_item("blank_field_map") is False
    assert agent.remove_item("task_journal") is False


def test_v034_shaped_agent_loads_with_defaults_and_structured_beliefs() -> None:
    agent = AgentState.from_dict({"name": "Ari", "inventory": {"branch": 2}, "beliefs": {"berries": "These berries may be edible."}, "explored": ["1,2"]})
    assert len(agent.key_items) == 3 and len(agent.tasks) == 4
    assert agent.beliefs["berries"].claim == "These berries may be edible."
    assert agent.beliefs["berries"].status == BeliefStatus.WORKING.value
    assert agent.beliefs["berries"].provenance.source_type == "legacy_migration"
    assert AgentState.from_dict(agent.to_dict()).to_dict() == agent.to_dict()


def test_unsupported_hypothesis_serializes_without_evidence() -> None:
    agent = AgentState()
    agent.beliefs["unproven"] = BeliefRecord("unproven", "The distant sound might be water.", 0.2, "A tentative inference.", BeliefStatus.HYPOTHESIS.value, 0.0, None, provenance=Provenance("inference"))
    restored = AgentState.from_dict(agent.to_dict())
    assert restored.beliefs["unproven"].supporting_evidence_ids == []
    assert restored.beliefs["unproven"].status == "hypothesis"


def test_view_actions_return_only_agent_knowledge_and_do_not_create_inventory_items() -> None:
    world = WorldState.generate(42, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.notes["n1"] = NoteRecord("n1", "Test", "Ari-authored note", [], "active", 0, 0, provenance=Provenance("agent"))
    agent.map_markers["m1"] = MapMarker("m1", "Possible water", "water", {"relative": "west"}, 0.4, "active", "uncertain", 0, 0, provenance=Provenance("inference"))
    controller = ActionController()
    agent.known_terrain["41,7"] = "known meadow"
    map_result = _complete(controller, world, agent, "view_map")
    assert "observer_truth_included" not in map_result.data
    assert "known_terrain" not in map_result.data
    serialized = json.dumps(map_result.data)
    assert "41,7" not in serialized
    assert "wolf" not in serialized and world.truth_notes["cave"] not in serialized
    assert len(_complete(controller, world, agent, "view_task_journal").data["tasks"]) == 4
    assert _complete(controller, world, agent, "view_notebook").data["notes"][0]["content"] == "Ari-authored note"
    assert agent.inventory == {}


def test_key_items_cannot_be_dropped() -> None:
    world = WorldState.generate(43, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    result = ActionController().start(_decision("drop", target_id="blank_field_map"), world, agent)
    assert not result.success and result.reason == "key_item_protected"


def test_awakening_appears_once_and_is_serialized() -> None:
    world = WorldState.generate(44, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    assert build_perception(world, agent)["awakening"] == AWAKENING_NARRATIVE
    _complete(ActionController(), world, agent, "view_task_journal")
    assert build_perception(world, agent)["awakening"] is None
    assert AgentState.from_dict(agent.to_dict()).awakening.presented is True


def test_snapshot_restart_and_reset_round_trip_all_cognitive_stores(engine, settings) -> None:
    engine.agent.notes["n1"] = NoteRecord("n1", "Note", "content", ["tag"], "active", 1, 1, provenance=Provenance("agent"))
    engine.agent.map_markers["m1"] = MapMarker("m1", "Marker", "unknown", {"relative": "north"}, 0.3, "active", "", 1, 1, provenance=Provenance("agent"))
    engine.agent.beliefs["b1"] = "A subjective working belief."
    engine.agent.short_term_episodes["e1"] = EpisodeRecord("e1", 1, 1, "episode", "test", 0.5, "recent", provenance=Provenance("agent"))
    expected = _cognition(AgentState.from_dict(engine.agent.to_dict()))
    engine.save_snapshot("cognition")
    assert _cognition(AgentState.from_dict(engine.snapshots.load("cognition")["agent"])) == expected
    engine.agent.notes.clear()
    engine.load_snapshot("cognition")
    assert _cognition(engine.agent) == expected
    engine._persist_current()
    database = Database(settings.database_path)
    from app.simulation.engine import SimulationEngine
    restored_engine = SimulationEngine(settings, database=database, load_existing=True)
    try:
        assert _cognition(restored_engine.agent) == expected
    finally:
        database.close()
    old_run, old_world = engine.run_id, engine.world_generation_id
    engine.reset(999)
    assert engine.run_id != old_run and engine.world_generation_id != old_world
    assert len(engine.agent.key_items) == 3 and len(engine.agent.tasks) == 4
    assert not engine.agent.notes and not engine.agent.map_markers and not engine.agent.short_term_episodes
    assert "b1" not in engine.agent.beliefs
    assert set(engine.agent.beliefs) == {"self", "world"}
    assert engine.agent.awakening.presented is False


def test_first_decision_prompt_is_compact_and_normal_prompt_omits_full_stores() -> None:
    world = WorldState.generate(45, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    for index in range(100):
        agent.notes[str(index)] = NoteRecord(str(index), f"Note {index}", "x" * 500, [], "active", 0, 0, provenance=Provenance("agent"))
    perception = build_perception(world, agent)
    prompt = decision_messages({"perception": perception, "action_affordances": {}, "active_plan": [], "retrieved_memories": [], "recent_outcomes": []})[-1]["content"]
    assert "Note 99" not in prompt
    assert len(prompt) < 50000
    assert perception["cognitive_tools"]["note_count"] == 100
