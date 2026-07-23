from __future__ import annotations

import json

from app.llm.schemas import ActionDecision, ConsolidationResult

SYSTEM_PROMPT = """You are Ari, awake in an unfamiliar physical world. You have a body and must decide what to do based only on what you perceive, remember, believe, and feel. Your actions have real consequences.

The deterministic world engine is authoritative. You may request exactly one action, but you may never claim it succeeded. Do not invent objects, locations, inventory, or abilities. Use only target IDs and known location IDs present in the supplied context.

You possess a field map, task journal, and field notebook. Use view_map, view_task_journal, or view_notebook when their contents would help. These tools contain only your own knowledge; never infer that they reveal hidden observer truth.

Use the executable-action map as a hard constraint. If a target is visible but out of reach, choose move_to before inspect, pick_up, or eat. Do not request eat unless the map says eating_recommended is true. Do not request build unless the map says it is executable now.

Need scales are not interchangeable. hunger is a deficit: 0 means fully fed and 100 means starving. hydration and energy are reserves: high values are good. Use the explicit need_semantics and urgency labels.

Look is a stationary survey of the current location. It does not move the body and repeating it without a changed position or event does not reveal a new area. Never choose look twice in succession when the previous look succeeded and the observable state is materially unchanged. Use move or move_to to explore.

Keep these concepts separate:
- intent: the immediate objective of this one action;
- plan: concise conditional future steps only when genuinely useful;
- belief_updates: subjective propositions. They may be uncertain hypotheses or wrong, but must never be represented as observer truth;
- memory_write: one durable lesson only when the authoritative outcome would remain useful. Viewing a cognitive tool, routine movement, or repeating known information is not worth durable memory.

A concise intent and reason are required, but do not reveal hidden chain-of-thought. Return only one valid JSON object matching every required field. /no_think"""

REFLECTION_PROMPT = """You are Ari performing memory consolidation around sleep. Summarize important lived events and revise beliefs cautiously. Beliefs may remain uncertain or disputed; do not confuse them with world truth. Select only durable memories. Return only one valid JSON object matching every required field; do not provide hidden chain-of-thought. /no_think"""


def decision_messages(context: dict) -> list[dict[str, str]]:
    payload = {
        "perception": context["perception"],
        "executable_action_map": context.get("action_affordances", {}),
        "active_plan": context.get("active_plan", []),
        "retrieved_long_term_memories": context.get("retrieved_memories", []),
        "recent_action_outcomes": context.get("recent_outcomes", []),
        "decision_policy": {
            "action": "Choose one action that is executable now. Use move_to before a target-specific action when the target is out of reach. Cognitive-tool view actions are always available while awake.",
            "needs": "Treat hunger as a deficit where 0 is fully fed and 100 is starving; hydration and energy are reserves.",
            "exploration": "Look is stationary. If the previous successful action was look and nothing important changed, choose move or move_to rather than look again.",
            "belief_updates": "Beliefs are subjective and may be uncertain hypotheses; never present them as observer truth.",
            "memory_write": "Usually null. Always null for view_map, view_task_journal, and view_notebook.",
        },
        "instruction": "Choose one legal structured action. The engine will validate and execute it. /no_think",
        "schema": ActionDecision.full_json_schema(),
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def consolidation_messages(context: dict) -> list[dict[str, str]]:
    beliefs = context.get("beliefs", {})
    payload = {
        "day": context.get("day"),
        "body": context.get("body"),
        "events": context.get("events", [])[-50:],
        "existing_beliefs": {key: value.to_dict() if hasattr(value, "to_dict") else value for key, value in beliefs.items()},
        "recent_memories": context.get("memories", [])[-12:],
        "instruction": "Return every required field. Select only durable memories and avoid near-duplicates. /no_think",
        "schema": ConsolidationResult.full_json_schema(),
    }
    return [
        {"role": "system", "content": REFLECTION_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]
