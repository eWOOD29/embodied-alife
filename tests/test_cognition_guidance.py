from __future__ import annotations

import json

from app.llm.prompts import decision_messages
from app.llm.schemas import ActionDecision, MemoryWrite
from app.simulation.affordances import build_action_affordances


def test_affordance_map_distinguishes_reachable_and_approach_targets(engine) -> None:
    engine.agent.hunger = 50.0
    perception = {
        "available_actions": ["move", "move_to", "inspect", "pick_up", "eat"],
        "visible_objects": [
            {
                "id": "near_food",
                "kind": "edible_plant",
                "distance": 1.2,
                "direction": "north",
                "portable": True,
                "appears_edible": True,
            },
            {
                "id": "far_branch",
                "kind": "branch",
                "distance": 4.0,
                "direction": "east",
                "portable": True,
                "appears_edible": False,
            },
        ],
        "visible_entities": [],
    }
    summary = build_action_affordances(engine.world, engine.agent, perception)
    assert set(summary["target_constraints"]["near_food"]["executable_now"]) == {"inspect", "pick_up", "eat"}
    assert summary["target_constraints"]["near_food"]["approach_action"] is None
    assert summary["target_constraints"]["far_branch"]["executable_now"] == []
    assert summary["target_constraints"]["far_branch"]["approach_action"] == "move_to"


def test_decision_prompt_includes_executable_map_and_memory_policy() -> None:
    messages = decision_messages(
        {
            "perception": {"visible_objects": [], "visible_entities": []},
            "action_affordances": {"currently_available_action_names": ["move"]},
            "active_plan": [],
            "retrieved_memories": [],
            "recent_outcomes": [],
        }
    )
    payload = json.loads(messages[1]["content"])
    assert payload["executable_action_map"]["currently_available_action_names"] == ["move"]
    assert "Usually null" in payload["decision_policy"]["memory_write"]
    assert "move_to" in payload["decision_policy"]["action"]


def test_routine_movement_memory_is_filtered(engine) -> None:
    decision = ActionDecision(
        intent="Approach a visible target.",
        action="move_to",
        target_id="resource_1",
        duration_seconds=3,
        interrupt_if=[],
        reason="Get closer.",
        plan=["Move closer", "Inspect if reachable"],
        belief_updates={},
        memory_write=MemoryWrite(
            category="affordances",
            title="Moved toward a thing",
            content="Ari moved toward a visible thing.",
            importance=0.9,
            tags=["movement"],
        ),
    )
    eligible, reason = engine._memory_candidate_policy(decision)
    assert eligible is False
    assert reason == "routine_action_not_durable"
