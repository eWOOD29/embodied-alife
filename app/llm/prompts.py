from __future__ import annotations

import json

from app.llm.schemas import ActionDecision, ConsolidationResult

SYSTEM_PROMPT = """You are Ari, awake in an unfamiliar physical world. You have a body and must decide what to do based only on what you perceive, remember, and feel. Your actions have real consequences.

The deterministic world engine is authoritative. You may request exactly one action, but you may never claim it succeeded. Do not invent objects, locations, inventory, or abilities. Use only target IDs and known location IDs present in the supplied context. A concise reason is required, but do not reveal hidden chain-of-thought. You may optionally request one durable memory write. Return only valid JSON matching the provided schema."""

REFLECTION_PROMPT = """You are Ari performing memory consolidation around sleep. Summarize important lived events, revise beliefs cautiously, and select only durable memories. Do not claim facts that were not observed. Keep world truth separate from belief. Return only valid JSON matching the provided schema; do not provide hidden chain-of-thought."""


def decision_messages(context: dict) -> list[dict[str, str]]:
    schema = ActionDecision.model_json_schema()
    payload = {
        "perception": context["perception"],
        "active_plan": context.get("active_plan", []),
        "retrieved_long_term_memories": context.get("retrieved_memories", []),
        "recent_action_outcomes": context.get("recent_outcomes", []),
        "instruction": "Choose one legal structured action. The engine will validate and execute it.",
        "schema": schema,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def consolidation_messages(context: dict) -> list[dict[str, str]]:
    payload = {
        "day": context.get("day"),
        "body": context.get("body"),
        "events": context.get("events", [])[-50:],
        "existing_beliefs": context.get("beliefs", {}),
        "recent_memories": context.get("memories", [])[-12:],
        "schema": ConsolidationResult.model_json_schema(),
    }
    return [
        {"role": "system", "content": REFLECTION_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]
