from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.schemas import ActionDecision


def test_missing_intent_is_repaired_from_reason() -> None:
    decision = ActionDecision.model_validate(
        {
            "action": "eat",
            "target_id": "berry_bush_033",
            "reason": "A visible edible resource may restore energy.",
        }
    )

    assert decision.intent == "A visible edible resource may restore energy."
    assert decision.action == "eat"
    assert decision.target_id == "berry_bush_033"


def test_missing_reason_is_repaired_from_intent() -> None:
    decision = ActionDecision.model_validate(
        {
            "intent": "Explore the nearby area.",
            "action": "move",
            "direction": "southwest",
        }
    )

    assert decision.reason == "Explore the nearby area."


def test_invalid_action_is_not_repaired() -> None:
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(
            {
                "intent": "Reach the target instantly.",
                "action": "teleport",
                "reason": "It would be faster.",
            }
        )
