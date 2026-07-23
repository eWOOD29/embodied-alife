from __future__ import annotations

from app.llm.observed_client import ObservedLocalLLMClient
from app.llm.prompts import SYSTEM_PROMPT, decision_messages
from app.llm.schemas import ActionDecision
from app.simulation.affordances import EAT_HUNGER_THRESHOLD, build_action_affordances


def _decision(action: str, *, target_id: str | None = None) -> ActionDecision:
    return ActionDecision(
        intent="Exercise need and loop policy.",
        action=action,
        target_id=target_id,
        direction=None,
        duration_seconds=1.0,
        interrupt_if=[],
        reason="Test proposal.",
        plan=["Repeat the current behavior"],
        belief_updates={"test": "unverified"},
        memory_write=None,
    )


def _context(engine, affordances: dict, recent: list[dict] | None = None) -> dict:
    return {
        "perception": {
            "body": {"facing": "north"},
            "visible_objects": [],
            "visible_entities": [],
        },
        "action_affordances": affordances,
        "active_plan": [],
        "retrieved_memories": [],
        "recent_outcomes": recent or [],
    }


def test_hunger_deficit_zero_means_well_fed_and_blocks_eating(engine) -> None:
    engine.agent.hunger = 1.2
    engine.agent.inventory["berry"] = 1
    perception = {
        "available_actions": ["look", "move", "eat"],
        "visible_objects": [],
        "visible_entities": [],
    }
    affordances = build_action_affordances(engine.world, engine.agent, perception)

    assert affordances["need_semantics"]["hunger_deficit"] == 1.2
    assert affordances["need_semantics"]["satiety"] == 98.8
    assert affordances["need_semantics"]["eating_recommended"] is False
    assert affordances["can_eat_from_inventory"] is False
    assert affordances["food_policy"]["can_eat_now"] is False

    client = object.__new__(ObservedLocalLLMClient)
    corrected, reason = client._apply_preexecution_policy(_decision("eat"), _context(engine, affordances))
    assert reason == "eat_blocked_while_satiated"
    assert corrected.action == "move"
    assert corrected.direction == "east"
    assert corrected.plan == []
    assert corrected.belief_updates == {}


def test_eating_is_allowed_after_hunger_threshold(engine) -> None:
    engine.agent.hunger = EAT_HUNGER_THRESHOLD + 5
    engine.agent.inventory["berry"] = 1
    perception = {
        "available_actions": ["look", "move", "eat"],
        "visible_objects": [],
        "visible_entities": [],
    }
    affordances = build_action_affordances(engine.world, engine.agent, perception)
    assert affordances["need_semantics"]["eating_recommended"] is True
    assert affordances["can_eat_from_inventory"] is True

    client = object.__new__(ObservedLocalLLMClient)
    unchanged, reason = client._apply_preexecution_policy(_decision("eat"), _context(engine, affordances))
    assert reason is None
    assert unchanged.action == "eat"


def test_second_successful_stationary_look_is_converted_to_movement(engine) -> None:
    affordances = {
        "need_semantics": {"eating_recommended": False},
        "food_policy": {"collect_more_food": True},
        "target_constraints": {},
    }
    recent = [
        {
            "action": "look",
            "target_id": None,
            "success": True,
            "reason": "observed",
            "details": "Ari deliberately surveyed the nearby area.",
        }
    ]
    client = object.__new__(ObservedLocalLLMClient)
    corrected, reason = client._apply_preexecution_policy(
        _decision("look"),
        _context(engine, affordances, recent),
    )
    assert reason == "consecutive_stationary_look"
    assert corrected.action == "move"
    assert corrected.direction == "east"


def test_prompt_explains_hunger_and_look_semantics(engine) -> None:
    assert "0 means fully fed and 100 means starving" in SYSTEM_PROMPT
    assert "Never choose look twice in succession" in SYSTEM_PROMPT
    context = _context(
        engine,
        {
            "need_semantics": {"hunger_deficit": 1.0, "eating_recommended": False},
            "food_policy": {"collect_more_food": True},
        },
    )
    rendered = str(decision_messages(context))
    assert "hunger as a deficit" in rendered
    assert "previous successful action was look" in rendered
