from __future__ import annotations

import copy
import json

from app.llm.fallback import FallbackBrain
from app.llm.prompts import ACTIVE_PLAN_LIMIT, MEMORY_LIMIT, decision_messages
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



def test_exact_marker_branch_uses_allowlist_and_preserves_observer_cognition() -> None:
    world = WorldState.generate(991, 48)
    agent = AgentState(x=17.0, y=23.0)
    forbidden_values = {
        "CAVE_TRUTH_SENTINEL", "RECIPE_SENTINEL", "HIDDEN_ENTITY_SENTINEL", "HIDDEN_RESOURCE_SENTINEL",
        "OBSERVER_ID_SENTINEL", "OBSERVER_CAMEL_SENTINEL", "INTERNAL_METADATA_SENTINEL", "TRUTH_SENTINEL",
        "COORDINATES_SENTINEL", "ABSOLUTE_POSITION_SENTINEL", "PRIVATE_PATH_SENTINEL", "NOTES_SENTINEL",
        "PROVENANCE_SENTINEL", "LINKED_METADATA_SENTINEL",
    }
    believed_location = {
        "relative_direction": "northwest",
        "distance_band": "near",
        "uncertainty": 0.3,
        "cave_truth": "CAVE_TRUTH_SENTINEL",
        "recipe": "RECIPE_SENTINEL",
        "hidden_entity": "HIDDEN_ENTITY_SENTINEL",
        "hidden_resource": "HIDDEN_RESOURCE_SENTINEL",
        "observer_id": "OBSERVER_ID_SENTINEL",
        "observerId": "OBSERVER_CAMEL_SENTINEL",
        "internal_metadata": {"truth": "INTERNAL_METADATA_SENTINEL"},
        "truth": "TRUTH_SENTINEL",
        "coordinates": "COORDINATES_SENTINEL",
        "absolute_position": "ABSOLUTE_POSITION_SENTINEL",
        "nested": [{"private_path": "PRIVATE_PATH_SENTINEL"}],
    }
    marker = MapMarker(
        "marker-safe", "possible landmark", "subjective", believed_location, 0.55, "active",
        "NOTES_SENTINEL", 0, 0,
        linked_task_ids=["LINKED_METADATA_SENTINEL"],
        linked_note_ids=["LINKED_METADATA_SENTINEL"],
        provenance=Provenance("observer", "OBSERVER_ID_SENTINEL", "PROVENANCE_SENTINEL"),
    )
    believed_location["extension"] = {"metadata": ["LINKED_METADATA_SENTINEL"]}
    agent.map_markers[marker.marker_id] = marker

    result = _complete(ActionController(), world, agent, "view_map")
    result_payload = result.to_dict()
    normal_prompt = decision_messages({
        "perception": build_perception(world, agent),
        "active_plan": [],
        "retrieved_memories": [],
        "recent_outcomes": [result_payload],
    })[-1]["content"]
    first_agent = AgentState.from_dict(agent.to_dict())
    first_agent.awakening.presented = False
    first_prompt = _serialized_prompt(world, first_agent)
    fallback = FallbackBrain().decide(build_perception(world, agent)).model_dump()

    forbidden_keys = {
        "x", "y", "world_x", "world_y", "coordinates", "absolute_position", "cave_truth", "recipe",
        "hidden_entity", "hidden_resource", "observer_id", "observerid", "internal_metadata", "truth",
        "nested", "extension", "private_path", "notes", "provenance", "source_id", "detail",
    }
    for payload in (result_payload, json.loads(normal_prompt), json.loads(first_prompt), fallback):
        _assert_forbidden(payload, forbidden_keys, forbidden_values)
    projected = result.data["markers"][0]
    assert projected == {
        "marker_id": "marker-safe",
        "label": "possible landmark",
        "marker_type": "subjective",
        "status": "active",
        "confidence": 0.55,
        "provenance_category": "subjective",
        "believed_location": {"direction": "northwest", "distance_band": "near", "uncertainty": 0.3},
    }
    observer = agent.to_dict()
    assert observer["map_markers"]["marker-safe"]["believed_location"]["cave_truth"] == "CAVE_TRUTH_SENTINEL"
    assert observer["map_markers"]["marker-safe"]["notes"] == "NOTES_SENTINEL"
    assert observer["map_markers"]["marker-safe"]["provenance"]["detail"] == "PROVENANCE_SENTINEL"



def _large_prompt_case(world: WorldState, size: int, *, awakening: bool) -> tuple[AgentState, str, dict]:
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.awakening.presented = not awakening
    agent.key_items = {}
    agent.tasks = {}
    agent.personality_traits = {}
    agent.known_locations = {}
    agent.recent_events = []
    memories = []
    active_plan = []
    for index in range(size):
        sentinel = f"FULL_STORE_SENTINEL_{size}_{index}_"
        key_id = sentinel + ("k" * 500)
        agent.key_items[key_id] = KeyItem(key_id, sentinel + ("d" * 500), "description", Provenance("test"))
        task_id = f"task-{index}"
        agent.tasks[task_id] = TaskRecord(task_id, sentinel + ("t" * 500), "summary" + ("s" * 500), "test", "proposed", index, 0, 0, provenance=Provenance("test"))
        agent.personality_traits[sentinel + ("p" * 300)] = sentinel + ("v" * 800)
        agent.known_locations[sentinel + ("l" * 400)] = {"x": index, "y": index, "certainty": sentinel + "bad"}
        agent.recent_events.append({"sim_time": sentinel, "kind": sentinel + ("e" * 300), "message": sentinel + ("m" * 900), "importance": sentinel})
        agent.beliefs[f"belief-{index}"] = BeliefRecord(f"belief-{index}", sentinel + ("b" * 900), 0.5, sentinel + ("q" * 900), "hypothesis", index, None, provenance=Provenance("test"))
        agent.notes[f"note-{index}"] = NoteRecord(f"note-{index}", sentinel, sentinel + ("n" * 900), [], "active", 0, 0, provenance=Provenance("test"))
        agent.map_markers[f"marker-{index}"] = MapMarker(f"marker-{index}", sentinel, "test", {"relative_direction": "north", "metadata": sentinel}, 0.5, "active", sentinel, 0, 0, provenance=Provenance("test"))
        agent.short_term_episodes[f"episode-{index}"] = EpisodeRecord(f"episode-{index}", index, index, sentinel + ("z" * 900), "test", 0.5, "recent", provenance=Provenance("test"))
        memories.append({"memory_id": f"memory-{index}", "title": sentinel + ("r" * 600), "content": sentinel + ("c" * 5000), "tags": [sentinel + ("g" * 500)] * 50})
        active_plan.append(sentinel + ("a" * 3000))
    perception = build_perception(world, agent)
    prompt = decision_messages({
        "perception": perception,
        "active_plan": active_plan,
        "retrieved_memories": memories,
        "recent_outcomes": [{"details": f"OUTCOME_FULL_SENTINEL_{index}_" + ("o" * 3000)} for index in range(size)],
    })[-1]["content"]
    return agent, prompt, json.loads(prompt)


def test_every_normal_prompt_source_has_fixed_final_bounds_at_three_scales() -> None:
    world = WorldState.generate(992, 48)
    results = [_large_prompt_case(world, size, awakening=False) for size in (10, 100, 1000)]
    lengths = [len(prompt) for _, prompt, _ in results]
    assert max(lengths) - min(lengths) < 2500
    for size, (agent, prompt, payload) in zip((10, 100, 1000), results):
        perception = payload["perception"]
        assert perception["cognitive_tools"]["task_count"] == size
        assert perception["cognitive_tools"]["note_count"] == size
        assert len(perception["cognitive_tools"]["key_item_ids"]) == min(size, 8)
        assert len(perception["cognitive_tools"]["proposed_task_titles"]) == min(size, 4)
        assert len(perception["personality_traits"]) == min(size, 12)
        assert len(payload["active_plan"]) == min(size, ACTIVE_PLAN_LIMIT)
        assert len(payload["retrieved_long_term_memories"]) == min(size, MEMORY_LIMIT)
        assert len(payload["recent_action_outcomes"]) <= 4
        assert all(len(item) <= 240 for item in payload["active_plan"])
        assert all(len(key) <= 96 for key in perception["cognitive_tools"]["key_item_ids"])
        assert all(len(title) <= 160 for title in perception["cognitive_tools"]["proposed_task_titles"])
        complete = f"FULL_STORE_SENTINEL_{size}_{size - 1}_" + ("c" * 5000)
        assert complete not in prompt
        assert f"OUTCOME_FULL_SENTINEL_{size - 1}_" + ("o" * 3000) not in prompt


def test_first_decision_uses_the_same_final_bounds() -> None:
    world = WorldState.generate(993, 48)
    _, first_prompt, first_payload = _large_prompt_case(world, 1000, awakening=True)
    _, normal_prompt, normal_payload = _large_prompt_case(world, 1000, awakening=False)
    assert "I wake beneath an unfamiliar sky" in first_prompt
    assert "I wake beneath an unfamiliar sky" not in normal_prompt
    assert len(first_payload["active_plan"]) == len(normal_payload["active_plan"]) == ACTIVE_PLAN_LIMIT
    assert abs(len(first_prompt) - len(normal_prompt)) < 4000
