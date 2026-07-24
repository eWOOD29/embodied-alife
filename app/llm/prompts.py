from __future__ import annotations

import json
import math
from typing import Any

from app.llm.schemas import ActionDecision, ConsolidationResult
from app.serialization import json_safe

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

DECISION_STRING_LIMIT = 240
DECISION_LIST_LIMIT = 12
DECISION_DICT_LIMIT = 40
DECISION_DEPTH_LIMIT = 7
ACTIVE_PLAN_LIMIT = 8
MEMORY_LIMIT = 6
OUTCOME_LIMIT = 4
MEMORY_TEXT_LIMIT = 400


def _text(value: Any, limit: int = DECISION_STRING_LIMIT) -> str:
    if not isinstance(value, (str, int, float, bool)):
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def _project(value: Any, *, depth: int = 0, list_limit: int = DECISION_LIST_LIMIT, dict_limit: int = DECISION_DICT_LIMIT) -> Any:
    if depth >= DECISION_DEPTH_LIMIT:
        return None
    if value is None or isinstance(value, bool):
        return value
    numeric = _number(value)
    if numeric is not None:
        return numeric
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item))[:dict_limit]:
            key = _text(raw_key, 96)
            if not key:
                continue
            projected = _project(value[raw_key], depth=depth + 1, list_limit=list_limit, dict_limit=dict_limit)
            if projected is not None:
                result[key] = projected
        return result
    if isinstance(value, (list, tuple, set)):
        source = sorted(value, key=lambda item: str(item)) if isinstance(value, set) else value
        result = []
        for item in list(source)[:list_limit]:
            projected = _project(item, depth=depth + 1, list_limit=list_limit, dict_limit=dict_limit)
            if projected is not None:
                result.append(projected)
        return result
    return None


def _plan_summary(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        text = _text(item)
        if text:
            result.append(text)
        if len(result) >= ACTIVE_PLAN_LIMIT:
            break
    return result


def _memory_summary(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        text = _text(raw, MEMORY_TEXT_LIMIT)
        return {"summary": text} if text else None
    result: dict[str, Any] = {}
    for key, limit in (("memory_id", 96), ("id", 96), ("category", 64), ("title", 160)):
        if key in raw and key not in result:
            text = _text(raw.get(key), limit)
            if text:
                result[key] = text
    summary = raw.get("summary", raw.get("content", raw.get("text", "")))
    text = _text(summary, MEMORY_TEXT_LIMIT)
    if text:
        result["summary"] = text
    importance = _number(raw.get("importance"))
    if importance is not None:
        result["importance"] = importance
    tags = _project(raw.get("tags", []), list_limit=8, dict_limit=0)
    if tags:
        result["tags"] = tags
    return result or None


def _memory_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for raw in value:
        summary = _memory_summary(raw)
        if summary:
            result.append(summary)
        if len(result) >= MEMORY_LIMIT:
            break
    return result


def decision_messages(context: dict) -> list[dict[str, str]]:
    payload = {
        "perception": _project(context.get("perception", {}), list_limit=64, dict_limit=64),
        "executable_action_map": _project(context.get("action_affordances", {}), list_limit=32, dict_limit=64),
        "active_plan": _plan_summary(context.get("active_plan", [])),
        "retrieved_long_term_memories": _memory_summaries(context.get("retrieved_memories", [])),
        "recent_action_outcomes": _project(context.get("recent_outcomes", []), list_limit=OUTCOME_LIMIT, dict_limit=32),
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
        {"role": "user", "content": json.dumps(json_safe(payload, max_depth=8, max_items=512, max_text=4000, max_nodes=50000), ensure_ascii=False, separators=(",", ":"), allow_nan=False)},
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
        {"role": "user", "content": json.dumps(json_safe(payload, max_depth=8, max_items=512, max_text=4000, max_nodes=50000), ensure_ascii=False, separators=(",", ":"), allow_nan=False)},
    ]
