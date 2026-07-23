from __future__ import annotations

from app.llm.schemas import ActionDecision
from app.simulation.affordances import INTERACTION_RADIUS


def _decision(action: str, target_id: str | None = None) -> ActionDecision:
    return ActionDecision(
        intent="Exercise loop prevention.",
        action=action,
        target_id=target_id,
        direction=None,
        duration_seconds=2.0,
        interrupt_if=[],
        reason="Test proposal.",
        plan=["Repeat the target action."],
        belief_updates={"test": "unverified"},
        memory_write=None,
    )


def test_controller_and_affordances_share_interaction_radius(engine) -> None:
    resource = next(item for item in engine.world.resources.values() if item.edible and item.quantity > 0)
    engine.agent.x = float(resource.x) + INTERACTION_RADIUS - 0.01
    engine.agent.y = float(resource.y)
    assert engine.controller._find_edible(resource.id, engine.world, engine.agent) == ("world", resource.id)


def test_out_of_range_target_action_is_corrected_to_move_to(engine) -> None:
    decision = _decision("eat", "berry_bush_test")
    affordances = {
        "can_eat_from_inventory": False,
        "target_constraints": {
            "berry_bush_test": {
                "direction": "north",
                "executable_now": [],
                "requires_move_to_for": ["inspect", "pick_up", "eat"],
                "approach_action": "move_to",
            }
        },
    }
    corrected, correction = engine._correct_decision(decision, affordances, [])
    assert corrected.action == "move_to"
    assert corrected.target_id == "berry_bush_test"
    assert corrected.memory_write is None
    assert corrected.belief_updates == {}
    assert correction["reason"] == "target_action_requires_approach"


def test_stale_target_is_corrected_to_look(engine) -> None:
    decision = _decision("eat", "depleted_bush")
    corrected, correction = engine._correct_decision(
        decision,
        {"can_eat_from_inventory": False, "target_constraints": {}},
        [],
    )
    assert corrected.action == "look"
    assert corrected.target_id is None
    assert correction["reason"] == "target_action_not_currently_executable"


def test_repeated_failed_action_target_pair_is_blocked(engine) -> None:
    decision = _decision("eat", "berry_bush_test")
    failures = [
        {
            "sim_time": 10.0,
            "action": "eat",
            "target_id": "berry_bush_test",
            "success": False,
            "reason": "no_edible_item",
        },
        {
            "sim_time": 12.0,
            "action": "eat",
            "target_id": "berry_bush_test",
            "success": False,
            "reason": "no_edible_item",
        },
    ]
    affordances = {
        "can_eat_from_inventory": False,
        "target_constraints": {
            "berry_bush_test": {
                "direction": "north",
                "executable_now": ["eat"],
                "requires_move_to_for": [],
                "approach_action": None,
            }
        },
    }
    corrected, correction = engine._correct_decision(decision, affordances, failures)
    assert corrected.action == "look"
    assert correction["reason"] == "repeated_recent_failure"
