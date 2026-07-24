from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from app.llm.client import BrainResult
from app.llm.fallback import FallbackBrain
from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision
from app.memory.vault import MemoryVault
from app.serialization import UNORDERED_OMITTED, json_safe, strict_json_dumps
from app.simulation.actions import ARI_TASK_LIMIT, ActionController, ActionResult
from app.simulation.affordances import build_action_affordances
from app.simulation.agent import AgentState
from app.simulation.cognition import BeliefRecord, EpisodeRecord, KeyItem, MapMarker, NoteRecord, Provenance, TaskRecord
from app.simulation.engine import SimulationEngine
from app.simulation.integrity import (
    attach_key,
    seal_deterministic_starters,
    seal_record,
    sign_payload,
    verify_payload,
    verify_record,
)
from app.simulation.perception import build_perception
from app.simulation.world import WorldState
from app.storage.database import Database

TEST_KEY = b"post5-adversarial-key".ljust(32, b"!")


class Hostile:
    def __float__(self) -> float:
        raise AssertionError("hostile numeric conversion must not run")

    def __int__(self) -> int:
        raise AssertionError("hostile integer conversion must not run")

    def __repr__(self) -> str:
        raise AssertionError("hostile repr must not run")

    def __str__(self) -> str:
        raise AssertionError("hostile str must not run")


class CountingList(list):
    def __init__(self, values: list[Any]) -> None:
        super().__init__(values)
        self.accesses = 0

    def __iter__(self) -> Iterator[Any]:
        for item in super().__iter__():
            self.accesses += 1
            yield item


class CountingMapping(Mapping[str, Any]):
    def __init__(self, count: int) -> None:
        self.count = count
        self.accesses = 0

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[str]:
        for index in range(self.count):
            self.accesses += 1
            yield f"key-{index}"

    def __getitem__(self, key: str) -> Any:
        return int(key.split("-")[-1])

    def items(self):
        for key in self:
            yield key, self[key]


class CountingSet(set):
    def __init__(self, values: set[int]) -> None:
        super().__init__(values)
        self.accesses = 0

    def __iter__(self) -> Iterator[int]:
        for item in super().__iter__():
            self.accesses += 1
            yield item


class CapturingBrain:
    def __init__(self) -> None:
        self.status = {"mode": "llm", "available": True}
        self.messages: list[dict[str, str]] | None = None

    async def check_status(self) -> dict[str, Any]:
        return self.status

    async def decide(self, context: dict[str, Any]) -> BrainResult[ActionDecision]:
        self.messages = decision_messages(context)
        return BrainResult(
            ActionDecision(
                intent="Continue after the bounded journal review.",
                action="wait",
                duration_seconds=0.2,
                reason="Production-chain post5 test.",
            ),
            "llm",
            "ok",
            latency_ms=1.0,
            prompt_tokens=10,
            completion_tokens=10,
        )

    def public_configuration(self) -> dict[str, Any]:
        return {"enabled": True, "status": self.status}


def _agent() -> AgentState:
    agent = AgentState(x=10.0, y=10.0)
    attach_key(agent, TEST_KEY)
    seal_deterministic_starters(agent, TEST_KEY)
    return agent


def _family_record(family: str, identity: str, text: str) -> Any:
    provenance = Provenance("agent")
    if family == "key_item":
        return KeyItem(identity, text, f"{text} description", provenance)
    if family == "task":
        return TaskRecord(identity, text, f"{text} description", "ari", "active", 1, 1.0, 1.0, provenance=provenance)
    if family == "note":
        return NoteRecord(identity, text, f"{text} content", ["safe"], "active", 1.0, 1.0, provenance=provenance)
    if family == "marker":
        return MapMarker(identity, text, "subjective", {"direction": "north"}, 0.5, "active", "", 1.0, 1.0, provenance=Provenance("perception"))
    if family == "belief":
        return BeliefRecord(identity, text, 0.5, "subjective", "working", 1.0, None, source_type="inference", provenance=Provenance("inference"))
    if family == "episode":
        return EpisodeRecord(identity, "event-1", 1.0, text, "observation", 0.5, "recent", provenance=Provenance("event"))
    raise AssertionError(family)


def _family_config(family: str) -> tuple[str, str, str]:
    if family == "marker":
        return "validated_perception", "perception", "label"
    if family == "belief":
        return "validated_model_response", "inference", "claim"
    if family == "episode":
        return "validated_action_event", "event", "summary"
    if family == "key_item":
        return "validated_model_response", "agent", "display_name"
    return "validated_model_response", "agent", "title"


def _clone(family: str, record: Any) -> Any:
    return type(record).from_dict(record.to_dict())


def _set_identity(family: str, record: Any, identity: str) -> None:
    field = {
        "key_item": "key_item_id",
        "task": "task_id",
        "note": "note_id",
        "marker": "marker_id",
        "belief": "belief_id",
        "episode": "episode_id",
    }[family]
    setattr(record, field, identity)


@pytest.mark.parametrize("family", ["key_item", "task", "note", "marker", "belief", "episode"])
def test_creation_path_proof_is_content_identity_and_origin_bound_for_every_record_family(family: str) -> None:
    agent = _agent()
    path, source, content_field = _family_config(family)
    safe = _family_record(family, "safe-id", f"SAFE_{family.upper()}")
    assert seal_record(family, safe, TEST_KEY, path, source_type=source, source_ref=f"source:{family}")
    assert verify_record(family, safe, agent)

    loaded = _clone(family, safe)
    assert verify_record(family, loaded, agent)
    assert json.dumps(loaded.to_dict(), sort_keys=True, allow_nan=False) == json.dumps(_clone(family, loaded).to_dict(), sort_keys=True, allow_nan=False)

    forged = _family_record(family, "forged-id", f"FORGED_{family.upper()}")
    forged.provenance.source_type = source
    forged.provenance.creation_path = path
    assert not verify_record(family, forged, agent)

    mutated = _clone(family, safe)
    setattr(mutated, content_field, f"MUTATED_{family.upper()}")
    assert not verify_record(family, mutated, agent)

    copied = _clone(family, safe)
    _set_identity(family, copied, "copied-id")
    assert not verify_record(family, copied, agent)

    mismatched_source = _clone(family, safe)
    mismatched_source.provenance.source_id = "different-source"
    assert not verify_record(family, mismatched_source, agent)

    conflicting = _clone(family, safe)
    conflicting.provenance.source_type = "unknown"
    assert not verify_record(family, conflicting, agent)

    missing = _clone(family, safe)
    missing.provenance.proof = None
    assert not verify_record(family, missing, agent)

    malformed = _clone(family, safe)
    malformed.provenance.proof = "not-a-proof"
    assert not verify_record(family, malformed, agent)

    restarted_agent = AgentState.from_dict(agent.to_dict())
    attach_key(restarted_agent, TEST_KEY)
    assert verify_record(family, _clone(family, safe), restarted_agent)


def test_linked_records_are_independently_authorized_with_cycles_duplicates_and_unsafe_outer_records() -> None:
    world = WorldState.generate(9101, 48)
    agent = _agent()
    agent.x, agent.y = float(world.spawn[0]), float(world.spawn[1])

    safe_note = NoteRecord("safe-note", "SAFE_LINKED_NOTE", "safe", [], "active", 1, 1, linked_task_ids=["safe-task"], provenance=Provenance("agent"))
    unsafe_note = NoteRecord("unsafe-note", "FORBIDDEN_LINKED_NOTE", "private", [], "active", 1, 1, provenance=Provenance("agent"))
    safe_task = TaskRecord("safe-task", "SAFE_OUTER_TASK", "safe", "ari", "active", 1, 1, 1, linked_note_ids=["safe-note", "unsafe-note"], provenance=Provenance("agent"))
    unsafe_task = TaskRecord("unsafe-task", "FORBIDDEN_OUTER_TASK", "private", "ari", "active", 2, 1, 1, linked_note_ids=["safe-note"], provenance=Provenance("agent"))
    duplicate_task = TaskRecord.from_dict(safe_task.to_dict())
    duplicate_task.title = "SAFE_DUPLICATE_ID"

    assert seal_record("note", safe_note, TEST_KEY, "validated_model_response", source_type="agent", source_ref="safe-note")
    assert seal_record("task", safe_task, TEST_KEY, "validated_model_response", source_type="agent", source_ref="safe-task")
    assert seal_record("task", duplicate_task, TEST_KEY, "validated_model_response", source_type="agent", source_ref="duplicate-task")
    agent.notes = {"safe-note": safe_note, "unsafe-note": unsafe_note}
    agent.tasks = {"safe": safe_task, "unsafe": unsafe_task, "duplicate-key": duplicate_task}

    result = _complete_view(world, agent, "view_task_journal")
    text = json.dumps(result.data, sort_keys=True, allow_nan=False)
    assert "SAFE_OUTER_TASK" in text
    assert "safe-note" in text
    assert "unsafe-note" not in text
    assert "FORBIDDEN" not in text
    assert sum(task["task_id"] == "safe-task" for task in result.data["tasks"]) == 1


def _complete_view(world: WorldState, agent: AgentState, action: str) -> ActionResult:
    controller = ActionController()
    decision = ActionDecision(intent="Review", action=action, duration_seconds=0.2, reason="Test")
    assert controller.start(decision, world, agent).success
    done, result, _ = controller.step(1.0, world, agent)
    assert done and result is not None and result.success
    return result


def test_recent_view_result_is_bound_to_the_same_verified_event(engine: SimulationEngine) -> None:
    valid = ActionResult(True, "view_notebook", "viewed", "safe", {"notes": [{"note_id": "safe", "title": "SAFE_VIEW", "content": "safe", "tags": [], "status": "active", "created_at": 0, "updated_at": 0, "provenance_category": "agent", "linked_task_ids": [], "linked_marker_ids": []}], "total_notes": 1, "total_active_notes": 1, "visible_notes": 1})
    engine._handle_action_result(valid)
    valid_event = next(event for event in reversed(engine.events) if event.get("kind") == "action_result" and event.get("data", {}).get("reason") == "viewed")
    forged_data = copy.deepcopy(valid_event["data"])
    forged_data["details"] = "FORBIDDEN_FORGED_EVENT"
    forged_data["data"]["notes"][0]["content"] = "FORBIDDEN_FORGED_VIEW_RESULT"
    engine.events.append({"id": "forged", "sim_time": 999, "kind": "action_result", "message": "forged", "importance": 1.0, "data": forged_data})

    outcomes = engine._recent_action_outcomes()
    text = json.dumps(outcomes, sort_keys=True, allow_nan=False)
    assert "SAFE_VIEW" in text
    assert "FORBIDDEN" not in text

    clean_payload = {key: value for key, value in valid_event["data"].items() if key != "_ari_integrity"}
    evidence = valid_event["data"]["_ari_integrity"]
    assert verify_payload(engine.agent, "recent_outcome", clean_payload, evidence)
    clean_payload["details"] = "changed"
    assert not verify_payload(engine.agent, "recent_outcome", clean_payload, evidence)


@pytest.mark.parametrize("count", [10, 100, 1000, 10000])
def test_serializer_bounds_ordered_source_access_and_output(count: int) -> None:
    source = CountingList(list(range(count)))
    result = json_safe(source, max_items=5, max_nodes=100, max_source_items=10)
    assert source.accesses <= 6
    assert isinstance(result, list) and len(result) <= 5
    strict_json_dumps(result)

    mapping = CountingMapping(count)
    mapped = json_safe(mapping, max_items=5, max_nodes=100, max_source_items=10)
    assert mapping.accesses <= 6
    assert isinstance(mapped, dict) and len(mapped) <= 5
    strict_json_dumps(mapped)


@pytest.mark.parametrize("count", [10, 100, 1000, 10000])
def test_serializer_omits_oversized_unordered_sources_without_iteration(count: int) -> None:
    source = CountingSet(set(range(count)))
    result = json_safe(source, max_items=5, max_nodes=100, max_source_items=10)
    assert result == [UNORDERED_OMITTED]
    assert source.accesses == 0


def test_serializer_distinguishes_cycles_from_repeated_references_and_handles_key_collisions() -> None:
    shared = {"value": 1}
    cycle: dict[str, Any] = {}
    cycle["self"] = cycle
    value = {1: shared, "1": shared, "cycle": cycle, "hostile": Hostile()}
    projected = json_safe(value, max_items=16, max_nodes=100, max_source_items=100)
    assert projected["1"] == {"value": 1}
    assert projected["1#2"] == {"value": 1}
    assert projected["cycle"]["self"] == "<circular>"
    assert projected["hostile"] == "<unsupported>"
    strict_json_dumps(projected)


@pytest.mark.parametrize(
    "awakening",
    [None, False, 0, "", True, 1, "truthy", [], [1], {}, {"presented": True}],
)
def test_agent_state_loading_is_type_aware_forward_safe_and_present_empty_stable(awakening: Any) -> None:
    raw = {
        "name": "Ari",
        "unknown_future_field": {"observer": "preserve-outside-constructor"},
        "awakening": awakening,
        "tasks": {},
        "key_items": {},
        "notes": "malformed",
        "map_markers": ["malformed"],
        "beliefs": object(),
        "short_term_episodes": True,
        "known_locations": [],
        "known_terrain": "bad",
        "explored": {"1,2"},
        "inventory": {"branch": "2", "bad": True, "hostile": Hostile()},
    }
    agent = AgentState.from_dict(raw)
    assert agent.tasks == {}
    assert agent.key_items == {}
    assert agent.notes == {}
    assert agent.map_markers == {}
    assert len(agent.beliefs) == 0
    assert agent.short_term_episodes == {}
    assert agent.known_locations == {}
    assert agent.known_terrain == {}
    assert agent.explored == {"1,2"}
    assert agent.inventory == {"branch": 2}
    assert not hasattr(agent, "unknown_future_field")
    assert AgentState.from_dict(agent.to_dict()).to_dict() == agent.to_dict()


def test_projection_paths_do_not_repair_or_replace_malformed_agent_collections() -> None:
    world = WorldState.generate(9102, 48)
    agent = _agent()
    agent.x, agent.y = float(world.spawn[0]), float(world.spawn[1])
    explored = ["malformed-explored"]
    terrain = ["malformed-terrain"]
    locations = "malformed-locations"
    tasks = ["malformed-tasks"]
    notes = "malformed-notes"
    markers = {"bad"}
    agent.explored = explored  # type: ignore[assignment]
    agent.known_terrain = terrain  # type: ignore[assignment]
    agent.known_locations = locations  # type: ignore[assignment]
    agent.tasks = tasks  # type: ignore[assignment]
    agent.notes = notes  # type: ignore[assignment]
    agent.map_markers = markers  # type: ignore[assignment]

    perception = build_perception(world, agent)
    affordances = build_action_affordances(world, agent, perception)
    decision_messages({"perception": perception, "action_affordances": affordances, "active_plan": [], "retrieved_memories": [], "recent_outcomes": []})
    _complete_view(world, agent, "view_map")

    assert agent.explored is explored
    assert agent.known_terrain is terrain
    assert agent.known_locations is locations
    assert agent.tasks is tasks
    assert agent.notes is notes
    assert agent.map_markers is markers


@pytest.mark.parametrize(
    "bad",
    [None, "", "bad", True, [], (), set(), b"12", {"nested": 1}, math.nan, math.inf, -math.inf, 10**500, Hostile()],
)
def test_affordance_normal_prompt_and_fallback_construct_strict_json_from_malformed_state(bad: Any) -> None:
    world = WorldState.generate(9103, 48)
    agent = _agent()
    agent.x = bad
    agent.y = bad
    agent.hunger = bad
    agent.hydration = bad
    agent.health = bad
    agent.energy = bad
    agent.sleep_pressure = bad
    agent.body_temperature_c = bad
    agent.pain = bad
    agent.inventory = {"berry": bad, "branch": bad, "stone": bad}

    perception = build_perception(world, agent)
    affordances = build_action_affordances(world, agent, perception)
    prompt = decision_messages({"perception": perception, "action_affordances": affordances, "active_plan": [], "retrieved_memories": [], "recent_outcomes": []})[-1]["content"]
    json.loads(prompt)
    fallback = FallbackBrain().decide(perception)
    json.dumps(fallback.model_dump(), allow_nan=False)
    assert affordances["position_known"] is False
    assert fallback.action in perception["available_actions"]


@pytest.mark.parametrize("count", [10, 100, 1000])
@pytest.mark.asyncio
async def test_real_production_chain_scale_is_bounded_persisted_restart_safe_and_excludes_forged_records(settings, count: int) -> None:
    database = Database(settings.database_path)
    engine = SimulationEngine(settings, database=database, vault=MemoryVault(settings.memory_dir), load_existing=False)
    key = engine._ari_integrity_key
    assert isinstance(key, bytes)
    engine.agent.tasks = {}
    safe = f"SAFE_PRODUCTION_CHAIN_{count}"
    forbidden = f"FORBIDDEN_PRODUCTION_CHAIN_{count}"
    for index in range(count):
        title = safe if index == 0 else (forbidden if index == count - 1 else f"task-{index}")
        record = TaskRecord(f"task-{index}", title, "useful", "ari", "active", index, float(index), float(index), provenance=Provenance("agent"))
        engine.agent.tasks[record.task_id] = record
        if index != count - 1:
            assert seal_record("task", record, key, "validated_model_response", source_type="agent", source_ref=f"scale:{index}")

    result = _complete_view(engine.world, engine.agent, "view_task_journal")
    immediate_text = json.dumps(result.to_dict(), sort_keys=True, allow_nan=False)
    assert safe in immediate_text
    assert forbidden not in immediate_text
    assert result.data["total_tasks"] == count - 1
    assert result.data["visible_tasks"] <= ARI_TASK_LIMIT
    assert len(immediate_text) < 30000

    engine._handle_action_result(result)
    engine._persist_current()
    persisted = database.get_metadata("current_state")
    assert forbidden in json.dumps(persisted["agent"]["tasks"], sort_keys=True, allow_nan=False)
    persisted_events = database.list_events(limit=1000)
    event_text = json.dumps(persisted_events, sort_keys=True, allow_nan=False)
    assert safe in event_text
    assert forbidden not in event_text
    database.close()

    restored_database = Database(settings.database_path)
    brain = CapturingBrain()
    restored = SimulationEngine(settings, database=restored_database, vault=MemoryVault(settings.memory_dir), brain=brain, load_existing=True)
    try:
        outcomes = restored._recent_action_outcomes()
        outcome_text = json.dumps(outcomes, sort_keys=True, allow_nan=False)
        assert safe in outcome_text
        assert forbidden not in outcome_text
        await restored.make_decision()
        assert brain.messages is not None
        prompt = brain.messages[-1]["content"]
        assert safe in prompt
        assert forbidden not in prompt
        assert len(prompt) < 30000
        assert prompt.count("view_result") <= 1
    finally:
        restored_database.close()
