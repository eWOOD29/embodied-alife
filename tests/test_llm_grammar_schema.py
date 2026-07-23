from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.schemas import ActionDecision, ConsolidationResult


def test_model_server_schema_is_minimal_json_object() -> None:
    assert ActionDecision.model_json_schema() == {"type": "object"}
    assert ConsolidationResult.model_json_schema() == {"type": "object"}


def test_full_action_validation_remains_enforced() -> None:
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(
            {
                "intent": "try an impossible action",
                "action": "teleport",
                "reason": "invalid action should still be rejected",
            }
        )
