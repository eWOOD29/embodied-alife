from __future__ import annotations

import json

from app.llm.prompts import consolidation_messages, decision_messages
from app.llm.schemas import ActionDecision, ConsolidationResult


def _decision_context() -> dict:
    return {
        "perception": {"body": {"hunger": 50}, "visible": []},
        "active_plan": [],
        "retrieved_memories": [],
        "recent_outcomes": [],
    }


def test_server_grammar_stays_minimal_but_prompt_schema_is_complete() -> None:
    assert ActionDecision.model_json_schema() == {"type": "object"}
    full_schema = ActionDecision.full_json_schema()
    required = set(full_schema["required"])
    assert {"intent", "action", "reason"}.issubset(required)
    assert "properties" in full_schema


def test_decision_prompt_disables_thinking_and_includes_full_contract() -> None:
    messages = decision_messages(_decision_context())
    assert "/no_think" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert "/no_think" in payload["instruction"]
    assert "intent" in payload["schema"]["properties"]
    assert "reason" in payload["schema"]["properties"]
    assert "action" in payload["schema"]["required"]


def test_consolidation_prompt_disables_thinking_and_includes_full_contract() -> None:
    messages = consolidation_messages({})
    assert "/no_think" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert "/no_think" in payload["instruction"]
    assert set(ConsolidationResult.full_json_schema()["required"]).issubset(
        set(payload["schema"]["required"])
    )
