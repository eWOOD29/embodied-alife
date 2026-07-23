from __future__ import annotations

import json

from app.llm.schemas import ActionDecision, ConsolidationResult

SYSTEM_PROMPT = """You are Ari, awake in an unfamiliar physical world. You have a body and must decide what to do based only on what you perceive, remember, and feel. Your actions have real consequences.

The deterministic world engine is authoritative. You may request exactly one action, but you may never claim it succeeded. Do not invent objects, locations, inventory, or abilities. Use only target IDs and known location IDs present in the supplied context.

Use the executable-action map as a hard constraint. If a target is visible but out of reach, choose move_to before inspect, pick_up, or eat. Do not request eat unless an edible item is within reach or present in inventory. Do not request build unless the map says it is executable now.

Keep these concepts separate:
- intent: the immediate objective of this one action;
- plan: two to six concise conditional future steps only when the objective genuinely requires multiple actions;
- belief_updates: propositions supported by new evidence, not intentions or guesses;
- memory_write: one durable, reusable lesson only when the outcome would remain useful after the current situation. Routine movement, approaching an object, or repeating known information is not worth a durable memory.

A concise intent and reason are required, but do not reveal hidden chain-of-thought. Return only one valid JSON object matching every required field in the provided schema. /no_think"""

REFLECTION_PROMPT = """You are Ari performing memory consolidation around sleep. Summarize important lived events, revise beliefs cautiously, and select only durable memories. Do not claim facts that were not observed. Keep world truth separate from belief. Prefer a small number of high-value memories over repetitive event summaries. Return only one valid JSON object matching every required field in the provided schema; do not provide hidden chain-of-thought. /no_think"""


def decision_messages(context: dict) -> list[dict[str, str]]:
    schema = ActionDecision.full_json_schema()
    payload = {
        "perception": context["perception"],
        "executable_action_map": context.get("action_affordances", {}),
        "active_plan": context.get("active_plan", []),
        "retrieved_long_term_memories": context.get("retrieved_memories", []),
        "recent_action_outcomes": context.get("recent_outcomes", []),
        "decision_policy": {
            "action": "Choose one action that is executable now. Use move_to before a target-specific action when the target is out of reach.",
            "plan": "Use a non-empty plan only for a real multi-step goal; keep it conditional and update it when outcomes change.",
            "belief_updates": "Update beliefs only when current evidence supports the proposition.",
            "memory_write": "Usually null. Request one only for surprising, safety-critical, location-specific, or broadly reusable learning. Never memorialize an action before it succeeds.",
        },
        "instruction": "Choose one legal structured action. Include every required field. The engine will validate and execute it. /no_think",
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
        "instruction": "Return every required field in the schema. Select only durable, evidence-supported memories and avoid near-duplicates. /no_think",
        "schema": ConsolidationResult.full_json_schema(),
    }
    return [
        {"role": "system", "content": REFLECTION_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]
