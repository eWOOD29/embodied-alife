from __future__ import annotations

import copy
import json

from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision
from app.simulation.actions import ActionController
from app.simulation.agent import AgentState
from app.simulation.cognition import (
    BeliefRecord,
    EpisodeRecord,
    KeyItem,
    MapMarker,
    NoteRecord,
    Provenance,
    TaskRecord,
)
from app.simulation.perception import BELIEF_SUMMARY_LIMIT, KNOWN_TILE_SUMMARY_LIMIT, build_perception
from app.simulation.world import WorldState


def _decision(action: str) -> ActionDecision:
    return ActionDecision(intent="semantic remediation test", action=action, duration_seconds=0.2, reason="test")


def _complete(controller: ActionController, world: WorldState, agent: AgentState, action: str):
    assert controller.start(_decision(action), world, agent).success
    completed, result, _ = controller.step(1.0, world, agent)
    assert completed and result is not None
    return result


def _serialized_prompt(world: WorldState, agent: AgentState) -> str:
    perception = build_perception(world, agent)
    return decision_messages({
        "perception": perception,
        "active_plan": [],
        "retrieved_memories": [],
        "recent_outcomes": [],
    })[-1]["content"]


def _assert_forbidden(value, forbidden_keys: set[str], forbidden_values: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert str(key).lower() not in forbidden_keys
            _assert_forbidden(item, forbidden_keys, forbidden_values)
    elif isinstance(value, list):
        for item in value:
            _assert_forbidden(item, forbidden_keys, forbidden_values)
    elif isinstance(value, str):
        for sentinel in forbidden_values:
            assert sentinel not in value


def test_view_map_and_normal_prompt_hide_absolute_and_hidden_sentinels() -> None:
    world = WorldState.generate(987, 48)
    agent = AgentState(x=17.0, y=23.0)
    agent.known_terrain = {
        "41,7": "ABSOLUTE_TERRAIN_SENTINEL",
        "3,39": "known meadow",
    }
    agent.known_locations["HIDDEN_LOCATION_SENTINEL"] = {
        "x": 41,
        "y": 7,
        "certainty": 0.8,
        "observer_id": "OBSERVER_ID_SENTINEL",
        "cave_truth": "CAVE_TRUTH_SENTINEL",
        "recipe": "RECIPE_SENTINEL",
        "resource": "RESOURCE_SENTINEL",
        "entity": "ENTITY_SENTINEL",
        "unexplored": "UNEXPLORED_SENTINEL",
    }
    agent.map_markers["marker"] = MapMarker(
        "marker", "subjective marker", "unknown", {"x": 41, "y": 7}, 0.4, "active", "Ari inference", 0, 0,
        provenance=Provenance("inference"),
    )
    result = _complete(ActionController(), world, agent, "view_map")
    assert "observer_truth_included" not in result.data
    assert "known_terrain" not in result.data
    assert result.data["known_cells"][0].keys() >= {"offset_east", "offset_south", "distance", "direction", "terrain"}
    serialized_map = json.dumps(result.data, sort_keys=True)
    prompt = _serialized_prompt(world, agent)
    forbidden_values = {
        "41,7", "3,39", "OBSERVER_ID_SENTINEL", "CAVE_TRUTH_SENTINEL", "RECIPE_SENTINEL",
        "RESOURCE_SENTINEL", "ENTITY_SENTINEL", "UNEXPLORED_SENTINEL",
    }
    forbidden_keys = {"x", "y", "world_x", "world_y", "observer_id", "cave_truth", "recipe", "resource", "entity", "unexplored"}
    _assert_forbidden(result.data, forbidden_keys, forbidden_values)
    for sentinel in forbidden_values:
        assert sentinel not in serialized_map
        assert sentinel not in prompt
    observer = agent.to_dict()
    assert observer["x"] == 17.0 and observer["y"] == 23.0
    assert "41,7" in observer["known_terrain"]


def test_belief_summary_and_all_store_prompt_growth_are_bounded() -> None:
    world = WorldState.generate(988, 48)
    small = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    large = AgentState.from_dict(small.to_dict())
    for index in range(400):
        unique = f"BELIEF_FULL_SENTINEL_{index}_" + ("b" * 800)
        large.beliefs[f"belief-{index:04d}"] = BeliefRecord(
            f"belief-{index:04d}", unique, 0.5, f"BASIS_FULL_SENTINEL_{index}_" + ("c" * 800),
            "hypothesis", float(index), None, provenance=Provenance("inference"),
        )
        large.notes[f"note-{index}"] = NoteRecord(
            f"note-{index}", f"NOTE_TITLE_SENTINEL_{index}", "n" * 900, [], "active", 0, 0,
            provenance=Provenance("test"),
        )
        large.tasks[f"task-{index}"] = TaskRecord(
            f"task-{index}", f"TASK_TITLE_SENTINEL_{index}", "t" * 900, "test", "proposed", index + 10, 0, 0,
            provenance=Provenance("test"),
        )
        large.map_markers[f"marker-{index}"] = MapMarker(
            f"marker-{index}", f"MARKER_LABEL_SENTINEL_{index}", "test", {"relative": "near"}, 0.5,
            "active", "m" * 900, 0, 0, provenance=Provenance("test"),
        )
        large.short_term_episodes[f"episode-{index}"] = EpisodeRecord(
            f"episode-{index}", index, index, f"EPISODE_SUMMARY_SENTINEL_{index}_" + ("e" * 900),
            "test", 0.5, "recent", provenance=Provenance("test"),
        )
    small_prompt = _serialized_prompt(world, small)
    large_prompt = _serialized_prompt(world, large)
    perception = build_perception(world, large)
    assert perception["belief_summary"]["total"] == 400 + len(small.beliefs)
    assert len(perception["belief_summary"]["selected"]) <= BELIEF_SUMMARY_LIMIT
    assert len(perception["previously_explored"]["nearby_known_tiles"]) <= KNOWN_TILE_SUMMARY_LIMIT
    assert len(large_prompt) - len(small_prompt) < 5000
    for sentinel in (
        "BELIEF_FULL_SENTINEL_0_", "BASIS_FULL_SENTINEL_0_", "NOTE_TITLE_SENTINEL_399",
        "TASK_TITLE_SENTINEL_399", "MARKER_LABEL_SENTINEL_399", "EPISODE_SUMMARY_SENTINEL_399_",
    ):
        assert sentinel not in large_prompt
    assert "belief_summary" in large_prompt
    assert '"total"' in large_prompt


def test_first_decision_awakening_and_normal_context_are_separately_bounded() -> None:
    world = WorldState.generate(989, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    full_claims = []
    for index in range(300):
        claim = f"FIRST_CONTEXT_SENTINEL_{index}_" + ("x" * 1000)
        full_claims.append(claim)
        agent.beliefs[f"b-{index}"] = claim
    first = _serialized_prompt(world, agent)
    assert "I wake beneath an unfamiliar sky" in first
    assert all(claim not in first for claim in full_claims)
    _complete(ActionController(), world, agent, "view_task_journal")
    normal = _serialized_prompt(world, agent)
    assert "I wake beneath an unfamiliar sky" not in normal
    assert all(claim not in normal for claim in full_claims)
    assert abs(len(first) - len(normal)) < 4000


def test_snapshot_restore_is_complete_payload_faithful_and_idempotent(engine) -> None:
    engine.agent.key_items = {}
    engine.agent.tasks = {}
    engine.agent.notes["n"] = NoteRecord("n", "title", "content", ["tag"], "active", 1, 2, provenance=Provenance("test"))
    engine.agent.map_markers["m"] = MapMarker("m", "label", "test", {"relative": "north"}, 0.4, "active", "note", 1, 2, provenance=Provenance("test"))
    engine.agent.beliefs["b"] = "unsupported subjective hypothesis"
    engine.agent.short_term_episodes["e"] = EpisodeRecord("e", 4, 2, "episode", "test", 0.6, "recent", provenance=Provenance("test"))
    engine.agent.recent_events.append({"sim_time": 2, "kind": "sentinel", "message": "history", "importance": 0.4, "data": {}})
    engine.last_action_result = {"sentinel": "last-action"}
    engine.last_decision = {"sentinel": "last-decision"}
    engine.pending_memory = {"sentinel": "pending-memory"}
    engine.memory_writes.append({"sentinel": "memory-write"})
    engine.run_id = "run-sentinel"
    engine.world_generation_id = "world-sentinel"
    engine.agent.awakening.presented = True
    engine.agent.awakening.presented_at = 12.0
    engine.save_snapshot("exact")
    expected = copy.deepcopy(engine.snapshots.load("exact"))
    engine.agent.notes.clear()
    engine.events.clear()
    engine.pending_memory = None
    engine.load_snapshot("exact")
    assert engine.serialize() == expected
    assert not any(event.get("message", "").startswith("Snapshot 'exact' loaded") for event in engine.serialize()["events"])
    engine.load_snapshot("exact")
    assert engine.serialize() == expected
    assert engine.database.get_metadata("last_snapshot_load_audit")["name"] == "exact"


def test_absent_and_empty_collections_have_distinct_migration_semantics(engine, settings) -> None:
    absent = AgentState.from_dict({"name": "Ari"})
    assert len(absent.key_items) == 3 and len(absent.tasks) == 4
    empty = AgentState.from_dict({"name": "Ari", "key_items": {}, "tasks": {}})
    assert empty.key_items == {} and empty.tasks == {}
    for _ in range(4):
        empty = AgentState.from_dict(empty.to_dict())
        assert empty.key_items == {} and empty.tasks == {}
    engine.agent.key_items = {}
    engine.agent.tasks = {}
    engine._persist_current()
    from app.simulation.engine import SimulationEngine
    from app.storage.database import Database
    restored = SimulationEngine(settings, database=Database(settings.database_path), load_existing=True)
    try:
        assert restored.agent.key_items == {} and restored.agent.tasks == {}
    finally:
        restored.database.close()
    engine.save_snapshot("empty")
    engine.agent.key_items = {"temporary": KeyItem("temporary", "temporary", "temporary", Provenance("test"))}
    engine.load_snapshot("empty")
    assert engine.agent.key_items == {} and engine.agent.tasks == {}
    engine.reset(123456)
    assert len(engine.agent.key_items) == 3 and len(engine.agent.tasks) == 4


def test_realistic_legacy_and_malformed_state_normalizes_without_truth_promotion() -> None:
    legacy = AgentState().to_dict()
    legacy.update({
        "name": "Ari", "x": 11.5, "y": 9.25, "current_action": {"action": "wait", "remaining": 2},
        "active_plan": ["observe", "rest"], "known_locations": {"water": {"x": 4, "y": 7, "certainty": 0.2}},
        "known_terrain": {"4,7": "shallow_water"}, "recent_events": [{"kind": "legacy", "message": "event"}],
        "retrieved_memories": [{"title": "memory"}], "personality_traits": {"curiosity": 0.9},
        "beliefs": {
            "string": "Water may be nearby.",
            "structured": {"claim": "The cave may be unsafe.", "confidence": 2.5, "basis": "inference", "status": "INVALID"},
            "malformed": {"confidence": "bad"},
        },
        "notes": ["not-a-dictionary"],
        "map_markers": {"bad": "not-a-record", "good": {"label": "possible camp", "confidence": -4, "status": "INVALID"}},
        "short_term_episodes": {"good": {"summary": "legacy episode", "salience": 4, "status": "INVALID"}, "bad": 9},
        "key_items": {}, "tasks": {},
    })
    restored = AgentState.from_dict(legacy)
    assert restored.key_items == {} and restored.tasks == {}
    assert restored.notes == {}
    assert set(restored.beliefs) == {"string", "structured"}
    assert restored.beliefs["string"].provenance.source_type == "legacy_migration"
    assert restored.beliefs["structured"].confidence == 1.0
    assert restored.beliefs["structured"].status == "hypothesis"
    assert restored.map_markers["good"].confidence == 0.0
    assert restored.map_markers["good"].status == "active"
    assert restored.short_term_episodes["good"].salience == 1.0
    assert restored.short_term_episodes["good"].status == "recent"
    assert AgentState.from_dict(restored.to_dict()).to_dict() == restored.to_dict()
