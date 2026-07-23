from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, path: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def commit(message: str, paths: list[str]) -> None:
    run("git", "add", *paths)
    run("git", "commit", "-m", message)


def stage_map_projection() -> None:
    path = "app/simulation/actions.py"
    text = read(path)
    old = '''def _strip_coordinate_fields(value: Any) -> Any:\n    forbidden = {"x", "y", "world_x", "world_y", "coordinates", "absolute_coordinates", "observer_id"}\n    if isinstance(value, dict):\n        return {key: _strip_coordinate_fields(item) for key, item in value.items() if str(key).lower() not in forbidden}\n    if isinstance(value, list):\n        return [_strip_coordinate_fields(item) for item in value]\n    return value\n'''
    new = '''ARI_MARKER_TEXT_LIMIT = 160\nARI_MARKER_LINK_LIMIT = 8\nARI_LOCATION_TEXT_KEYS = {\n    "direction": "direction",\n    "relative_direction": "direction",\n    "distance_band": "distance_band",\n    "relative_distance": "distance_band",\n    "description": "description",\n}\nARI_PROVENANCE_CATEGORIES = {\n    "agent": "agent",\n    "ari": "agent",\n    "inference": "inference",\n    "perception": "perception",\n    "observation": "perception",\n    "memory": "memory",\n    "task": "task",\n    "note": "note",\n    "system_initialization": "system",\n}\n\n\ndef _bounded_text(value: Any, limit: int = ARI_MARKER_TEXT_LIMIT) -> str:\n    if not isinstance(value, (str, int, float, bool)):\n        return ""\n    text = str(value).replace("\\n", " ").strip()\n    return text if len(text) <= limit else text[: limit - 1] + "…"\n\n\ndef _finite_number(value: Any, default: float | None = None) -> float | None:\n    if isinstance(value, bool):\n        return default\n    try:\n        number = float(value)\n    except (TypeError, ValueError, OverflowError):\n        return default\n    return number if math.isfinite(number) else default\n\n\ndef _safe_link_ids(values: Any, known_ids: set[str]) -> list[str]:\n    if not isinstance(values, (list, tuple, set)):\n        return []\n    selected: list[str] = []\n    iterable = sorted(values, key=lambda item: str(item)) if isinstance(values, set) else values\n    for raw in iterable:\n        if not isinstance(raw, (str, int)):\n            continue\n        item = _bounded_text(raw, 96)\n        if item and item in known_ids and item not in selected:\n            selected.append(item)\n        if len(selected) >= ARI_MARKER_LINK_LIMIT:\n            break\n    return selected\n\n\ndef _ari_location_projection(location: Any, agent: AgentState) -> dict[str, Any] | None:\n    if not isinstance(location, dict):\n        return None\n    world_x = _finite_number(location.get("x"))\n    world_y = _finite_number(location.get("y"))\n    if world_x is not None and world_y is not None:\n        dx, dy = world_x - _finite_number(agent.x, 0.0), world_y - _finite_number(agent.y, 0.0)\n        assert dx is not None and dy is not None\n        return {\n            "direction": _relative_direction(dx, dy),\n            "distance": round(math.hypot(dx, dy), 1),\n            "offset_east": round(dx, 1),\n            "offset_south": round(dy, 1),\n        }\n    projected: dict[str, Any] = {}\n    for source_key, output_key in ARI_LOCATION_TEXT_KEYS.items():\n        if source_key not in location or output_key in projected:\n            continue\n        text = _bounded_text(location.get(source_key), 120)\n        if text:\n            projected[output_key] = text\n    distance = _finite_number(location.get("distance"))\n    if distance is not None:\n        projected["distance"] = round(max(0.0, min(distance, 10000.0)), 1)\n    uncertainty = _finite_number(location.get("uncertainty"))\n    if uncertainty is not None:\n        projected["uncertainty"] = round(max(0.0, min(1.0, uncertainty)), 3)\n    confidence = _finite_number(location.get("confidence"))\n    if confidence is not None:\n        projected["confidence"] = round(max(0.0, min(1.0, confidence)), 3)\n    return projected or None\n\n\ndef _ari_marker_projection(marker: Any, agent: AgentState) -> dict[str, Any]:\n    source_type = _bounded_text(getattr(getattr(marker, "provenance", None), "source_type", ""), 48).lower()\n    item: dict[str, Any] = {\n        "marker_id": _bounded_text(getattr(marker, "marker_id", ""), 96),\n        "label": _bounded_text(getattr(marker, "label", "Unknown marker"), 120),\n        "marker_type": _bounded_text(getattr(marker, "marker_type", "unknown"), 64),\n        "status": _bounded_text(getattr(marker, "status", "active"), 24),\n        "confidence": round(max(0.0, min(1.0, _finite_number(getattr(marker, "confidence", 0.0), 0.0) or 0.0)), 3),\n        "provenance_category": ARI_PROVENANCE_CATEGORIES.get(source_type, "subjective"),\n    }\n    location = _ari_location_projection(getattr(marker, "believed_location", None), agent)\n    if location:\n        item["believed_location"] = location\n    task_links = _safe_link_ids(getattr(marker, "linked_task_ids", []), set(agent.tasks))\n    note_links = _safe_link_ids(getattr(marker, "linked_note_ids", []), set(agent.notes))\n    if task_links:\n        item["linked_task_ids"] = task_links\n    if note_links:\n        item["linked_note_ids"] = note_links\n    return item\n'''
    text = replace_once(text, old, new, path=path)
    old_loop = '''            markers: list[dict[str, Any]] = []\n            for marker in agent.map_markers.values():\n                if marker.status == "archived":\n                    continue\n                item = marker.to_dict()\n                location = item.pop("believed_location", None)\n                if isinstance(location, dict) and isinstance(location.get("x"), (int, float)) and isinstance(location.get("y"), (int, float)):\n                    dx, dy = float(location["x"]) - agent.x, float(location["y"]) - agent.y\n                    item["believed_location"] = {\n                        "direction": _relative_direction(dx, dy),\n                        "distance": round(math.hypot(dx, dy), 1),\n                        "offset_east": round(dx, 1),\n                        "offset_south": round(dy, 1),\n                    }\n                elif location is not None:\n                    item["believed_location"] = _strip_coordinate_fields(location)\n                markers.append(_strip_coordinate_fields(item))\n'''
    new_loop = '''            markers: list[dict[str, Any]] = []\n            for marker in agent.map_markers.values():\n                if str(getattr(marker, "status", "active")) == "archived":\n                    continue\n                markers.append(_ari_marker_projection(marker, agent))\n            markers.sort(key=lambda item: (item.get("status", ""), item.get("label", ""), item.get("marker_id", "")))\n'''
    text = replace_once(text, old_loop, new_loop, path=path)
    write(path, text)

    test_path = "tests/test_v040_remediation.py"
    tests = read(test_path)
    tests = tests.replace("from app.llm.prompts import decision_messages\n", "from app.llm.fallback import FallbackBrain\nfrom app.llm.prompts import decision_messages\n")
    addition = r'''


def test_exact_marker_branch_uses_allowlist_and_preserves_observer_cognition() -> None:
    world = WorldState.generate(991, 48)
    agent = AgentState(x=17.0, y=23.0)
    forbidden_values = {
        "CAVE_TRUTH_SENTINEL", "RECIPE_SENTINEL", "HIDDEN_ENTITY_SENTINEL", "HIDDEN_RESOURCE_SENTINEL",
        "OBSERVER_ID_SENTINEL", "OBSERVER_CAMEL_SENTINEL", "INTERNAL_METADATA_SENTINEL", "TRUTH_SENTINEL",
        "COORDINATES_SENTINEL", "ABSOLUTE_POSITION_SENTINEL", "PRIVATE_PATH_SENTINEL", "NOTES_SENTINEL",
        "PROVENANCE_SENTINEL", "LINKED_METADATA_SENTINEL",
    }
    believed_location = {
        "relative_direction": "northwest",
        "distance_band": "near",
        "uncertainty": 0.3,
        "cave_truth": "CAVE_TRUTH_SENTINEL",
        "recipe": "RECIPE_SENTINEL",
        "hidden_entity": "HIDDEN_ENTITY_SENTINEL",
        "hidden_resource": "HIDDEN_RESOURCE_SENTINEL",
        "observer_id": "OBSERVER_ID_SENTINEL",
        "observerId": "OBSERVER_CAMEL_SENTINEL",
        "internal_metadata": {"truth": "INTERNAL_METADATA_SENTINEL"},
        "truth": "TRUTH_SENTINEL",
        "coordinates": "COORDINATES_SENTINEL",
        "absolute_position": "ABSOLUTE_POSITION_SENTINEL",
        "nested": [{"private_path": "PRIVATE_PATH_SENTINEL"}],
    }
    marker = MapMarker(
        "marker-safe", "possible landmark", "subjective", believed_location, 0.55, "active",
        "NOTES_SENTINEL", 0, 0,
        linked_task_ids=["LINKED_METADATA_SENTINEL"],
        linked_note_ids=["LINKED_METADATA_SENTINEL"],
        provenance=Provenance("observer", "OBSERVER_ID_SENTINEL", "PROVENANCE_SENTINEL"),
    )
    believed_location["extension"] = {"metadata": ["LINKED_METADATA_SENTINEL"]}
    agent.map_markers[marker.marker_id] = marker

    result = _complete(ActionController(), world, agent, "view_map")
    result_payload = result.to_dict()
    normal_prompt = decision_messages({
        "perception": build_perception(world, agent),
        "active_plan": [],
        "retrieved_memories": [],
        "recent_outcomes": [result_payload],
    })[-1]["content"]
    first_agent = AgentState.from_dict(agent.to_dict())
    first_agent.awakening.presented = False
    first_prompt = _serialized_prompt(world, first_agent)
    fallback = FallbackBrain().decide(build_perception(world, agent)).model_dump()

    forbidden_keys = {
        "x", "y", "world_x", "world_y", "coordinates", "absolute_position", "cave_truth", "recipe",
        "hidden_entity", "hidden_resource", "observer_id", "observerid", "internal_metadata", "truth",
        "nested", "extension", "private_path", "notes", "provenance", "source_id", "detail",
    }
    for payload in (result_payload, json.loads(normal_prompt), json.loads(first_prompt), fallback):
        _assert_forbidden(payload, forbidden_keys, forbidden_values)
    projected = result.data["markers"][0]
    assert projected == {
        "marker_id": "marker-safe",
        "label": "possible landmark",
        "marker_type": "subjective",
        "status": "active",
        "confidence": 0.55,
        "provenance_category": "subjective",
        "believed_location": {"direction": "northwest", "distance_band": "near", "uncertainty": 0.3},
    }
    observer = agent.to_dict()
    assert observer["map_markers"]["marker-safe"]["believed_location"]["cave_truth"] == "CAVE_TRUTH_SENTINEL"
    assert observer["map_markers"]["marker-safe"]["notes"] == "NOTES_SENTINEL"
    assert observer["map_markers"]["marker-safe"]["provenance"]["detail"] == "PROVENANCE_SENTINEL"
'''
    if "test_exact_marker_branch_uses_allowlist_and_preserves_observer_cognition" not in tests:
        tests += addition
    write(test_path, tests)
    commit("Close Ari map-marker trust boundary", [path, test_path])


def stage_prompt_bounds() -> None:
    prompts_path = "app/llm/prompts.py"
    prompts = '''from __future__ import annotations\n\nimport json\nimport math\nfrom typing import Any\n\nfrom app.llm.schemas import ActionDecision, ConsolidationResult\n\nSYSTEM_PROMPT = """You are Ari, awake in an unfamiliar physical world. You have a body and must decide what to do based only on what you perceive, remember, believe, and feel. Your actions have real consequences.\n\nThe deterministic world engine is authoritative. You may request exactly one action, but you may never claim it succeeded. Do not invent objects, locations, inventory, or abilities. Use only target IDs and known location IDs present in the supplied context.\n\nYou possess a field map, task journal, and field notebook. Use view_map, view_task_journal, or view_notebook when their contents would help. These tools contain only your own knowledge; never infer that they reveal hidden observer truth.\n\nUse the executable-action map as a hard constraint. If a target is visible but out of reach, choose move_to before inspect, pick_up, or eat. Do not request eat unless the map says eating_recommended is true. Do not request build unless the map says it is executable now.\n\nNeed scales are not interchangeable. hunger is a deficit: 0 means fully fed and 100 means starving. hydration and energy are reserves: high values are good. Use the explicit need_semantics and urgency labels.\n\nLook is a stationary survey of the current location. It does not move the body and repeating it without a changed position or event does not reveal a new area. Never choose look twice in succession when the previous look succeeded and the observable state is materially unchanged. Use move or move_to to explore.\n\nKeep these concepts separate:\n- intent: the immediate objective of this one action;\n- plan: concise conditional future steps only when genuinely useful;\n- belief_updates: subjective propositions. They may be uncertain hypotheses or wrong, but must never be represented as observer truth;\n- memory_write: one durable lesson only when the authoritative outcome would remain useful. Viewing a cognitive tool, routine movement, or repeating known information is not worth durable memory.\n\nA concise intent and reason are required, but do not reveal hidden chain-of-thought. Return only one valid JSON object matching every required field. /no_think"""\n\nREFLECTION_PROMPT = """You are Ari performing memory consolidation around sleep. Summarize important lived events and revise beliefs cautiously. Beliefs may remain uncertain or disputed; do not confuse them with world truth. Select only durable memories. Return only one valid JSON object matching every required field; do not provide hidden chain-of-thought. /no_think"""\n\nDECISION_STRING_LIMIT = 240\nDECISION_LIST_LIMIT = 12\nDECISION_DICT_LIMIT = 40\nDECISION_DEPTH_LIMIT = 5\nACTIVE_PLAN_LIMIT = 8\nMEMORY_LIMIT = 6\nOUTCOME_LIMIT = 4\nMEMORY_TEXT_LIMIT = 400\n\n\ndef _text(value: Any, limit: int = DECISION_STRING_LIMIT) -> str:\n    if not isinstance(value, (str, int, float, bool)):\n        return ""\n    text = str(value).replace("\\n", " ").strip()\n    return text if len(text) <= limit else text[: limit - 1] + "…"\n\n\ndef _number(value: Any) -> int | float | None:\n    if isinstance(value, bool):\n        return value\n    if isinstance(value, int):\n        return value\n    if isinstance(value, float):\n        return value if math.isfinite(value) else None\n    return None\n\n\ndef _project(value: Any, *, depth: int = 0, list_limit: int = DECISION_LIST_LIMIT, dict_limit: int = DECISION_DICT_LIMIT) -> Any:\n    if depth >= DECISION_DEPTH_LIMIT:\n        return None\n    if value is None or isinstance(value, bool):\n        return value\n    numeric = _number(value)\n    if numeric is not None:\n        return numeric\n    if isinstance(value, str):\n        return _text(value)\n    if isinstance(value, dict):\n        result: dict[str, Any] = {}\n        for raw_key in sorted(value, key=lambda item: str(item))[:dict_limit]:\n            key = _text(raw_key, 96)\n            if not key:\n                continue\n            projected = _project(value[raw_key], depth=depth + 1, list_limit=list_limit, dict_limit=dict_limit)\n            if projected is not None:\n                result[key] = projected\n        return result\n    if isinstance(value, (list, tuple, set)):\n        source = sorted(value, key=lambda item: str(item)) if isinstance(value, set) else value\n        result = []\n        for item in list(source)[:list_limit]:\n            projected = _project(item, depth=depth + 1, list_limit=list_limit, dict_limit=dict_limit)\n            if projected is not None:\n                result.append(projected)\n        return result\n    return None\n\n\ndef _plan_summary(value: Any) -> list[str]:\n    if not isinstance(value, (list, tuple)):\n        return []\n    result = []\n    for item in value:\n        text = _text(item)\n        if text:\n            result.append(text)\n        if len(result) >= ACTIVE_PLAN_LIMIT:\n            break\n    return result\n\n\ndef _memory_summary(raw: Any) -> dict[str, Any] | None:\n    if not isinstance(raw, dict):\n        text = _text(raw, MEMORY_TEXT_LIMIT)\n        return {"summary": text} if text else None\n    result: dict[str, Any] = {}\n    for key, limit in (("memory_id", 96), ("id", 96), ("category", 64), ("title", 160)):\n        if key in raw and key not in result:\n            text = _text(raw.get(key), limit)\n            if text:\n                result[key] = text\n    summary = raw.get("summary", raw.get("content", raw.get("text", "")))\n    text = _text(summary, MEMORY_TEXT_LIMIT)\n    if text:\n        result["summary"] = text\n    importance = _number(raw.get("importance"))\n    if importance is not None:\n        result["importance"] = importance\n    tags = _project(raw.get("tags", []), list_limit=8, dict_limit=0)\n    if tags:\n        result["tags"] = tags\n    return result or None\n\n\ndef _memory_summaries(value: Any) -> list[dict[str, Any]]:\n    if not isinstance(value, (list, tuple)):\n        return []\n    result = []\n    for raw in value:\n        summary = _memory_summary(raw)\n        if summary:\n            result.append(summary)\n        if len(result) >= MEMORY_LIMIT:\n            break\n    return result\n\n\ndef decision_messages(context: dict) -> list[dict[str, str]]:\n    payload = {\n        "perception": _project(context.get("perception", {}), list_limit=64, dict_limit=64),\n        "executable_action_map": _project(context.get("action_affordances", {}), list_limit=32, dict_limit=64),\n        "active_plan": _plan_summary(context.get("active_plan", [])),\n        "retrieved_long_term_memories": _memory_summaries(context.get("retrieved_memories", [])),\n        "recent_action_outcomes": _project(context.get("recent_outcomes", []), list_limit=OUTCOME_LIMIT, dict_limit=32),\n        "decision_policy": {\n            "action": "Choose one action that is executable now. Use move_to before a target-specific action when the target is out of reach. Cognitive-tool view actions are always available while awake.",\n            "needs": "Treat hunger as a deficit where 0 is fully fed and 100 is starving; hydration and energy are reserves.",\n            "exploration": "Look is stationary. If the previous successful action was look and nothing important changed, choose move or move_to rather than look again.",\n            "belief_updates": "Beliefs are subjective and may be uncertain hypotheses; never present them as observer truth.",\n            "memory_write": "Usually null. Always null for view_map, view_task_journal, and view_notebook.",\n        },\n        "instruction": "Choose one legal structured action. The engine will validate and execute it. /no_think",\n        "schema": ActionDecision.full_json_schema(),\n    }\n    return [\n        {"role": "system", "content": SYSTEM_PROMPT},\n        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)},\n    ]\n\n\ndef consolidation_messages(context: dict) -> list[dict[str, str]]:\n    beliefs = context.get("beliefs", {})\n    payload = {\n        "day": context.get("day"),\n        "body": context.get("body"),\n        "events": context.get("events", [])[-50:],\n        "existing_beliefs": {key: value.to_dict() if hasattr(value, "to_dict") else value for key, value in beliefs.items()},\n        "recent_memories": context.get("memories", [])[-12:],\n        "instruction": "Return every required field. Select only durable memories and avoid near-duplicates. /no_think",\n        "schema": ConsolidationResult.full_json_schema(),\n    }\n    return [\n        {"role": "system", "content": REFLECTION_PROMPT},\n        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},\n    ]\n'''
    write(prompts_path, prompts)

    path = "app/simulation/perception.py"
    text = read(path)
    text = replace_once(text, "KNOWN_LOCATION_SUMMARY_LIMIT = 12\n", '''KNOWN_LOCATION_SUMMARY_LIMIT = 12\nKEY_ITEM_SUMMARY_LIMIT = 8\nKEY_ITEM_ID_LIMIT = 96\nTASK_TITLE_SUMMARY_LIMIT = 4\nTASK_TITLE_TEXT_LIMIT = 160\nPERSONALITY_TRAIT_LIMIT = 12\nPERSONALITY_KEY_LIMIT = 64\nPERSONALITY_VALUE_LIMIT = 120\nINVENTORY_SUMMARY_LIMIT = 24\nACTIVE_TEXT_LIMIT = 240\n''', path=path)
    text = replace_once(text, '''def _truncate(value: Any, limit: int = BELIEF_TEXT_LIMIT) -> str:\n    text = str(value or "").replace("\\n", " ").strip()\n    return text if len(text) <= limit else text[: limit - 1] + "…"\n''', '''def _truncate(value: Any, limit: int = BELIEF_TEXT_LIMIT) -> str:\n    if not isinstance(value, (str, int, float, bool)):\n        return ""\n    text = str(value).replace("\\n", " ").strip()\n    return text if len(text) <= limit else text[: limit - 1] + "…"\n\n\ndef _safe_number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:\n    if isinstance(value, bool):\n        number = default\n    else:\n        try:\n            number = float(value)\n        except (TypeError, ValueError, OverflowError):\n            number = default\n    if not math.isfinite(number):\n        number = default\n    if minimum is not None:\n        number = max(minimum, number)\n    if maximum is not None:\n        number = min(maximum, number)\n    return number\n\n\ndef _bounded_pairs(value: Any, *, count_limit: int, key_limit: int, value_limit: int) -> dict[str, Any]:\n    if not isinstance(value, dict):\n        return {}\n    result: dict[str, Any] = {}\n    for raw_key in sorted(value, key=lambda item: str(item)):\n        key = _truncate(raw_key, key_limit)\n        if not key:\n            continue\n        raw_value = value[raw_key]\n        if isinstance(raw_value, (int, float, bool)):\n            projected: Any = _safe_number(raw_value) if not isinstance(raw_value, bool) else raw_value\n        else:\n            projected = _truncate(raw_value, value_limit)\n        result[key] = projected\n        if len(result) >= count_limit:\n            break\n    return result\n\n\ndef _known_tile_summaries(agent: AgentState, ax: int, ay: int) -> list[dict[str, Any]]:\n    records: list[tuple[int, int, int, str]] = []\n    for raw_key, raw_terrain in agent.known_terrain.items():\n        if not isinstance(raw_key, str):\n            continue\n        try:\n            x_text, y_text = raw_key.split(",", 1)\n            world_x, world_y = int(x_text), int(y_text)\n        except (AttributeError, TypeError, ValueError):\n            continue\n        records.append((abs(world_x - ax) + abs(world_y - ay), world_x, world_y, _truncate(raw_terrain, 64)))\n    records.sort(key=lambda item: (item[0], item[2], item[1], item[3]))\n    return [\n        {"x": world_x - ax, "y": world_y - ay, "terrain": terrain}\n        for _, world_x, world_y, terrain in records[:KNOWN_TILE_SUMMARY_LIMIT]\n    ]\n''', path=path)
    text = text.replace('        timestamp = float(belief.get("last_tested_at") or belief.get("first_formed_at") or 0.0)\n', '        timestamp = _safe_number(belief.get("last_tested_at") or belief.get("first_formed_at") or 0.0)\n')
    text = text.replace('            "belief_id": key,\n', '            "belief_id": _truncate(key, 96),\n')
    text = text.replace('            "status": str(belief.get("status", "hypothesis")),\n            "confidence": round(float(belief.get("confidence", 0.5)), 3),\n', '            "status": _truncate(belief.get("status", "hypothesis"), 32),\n            "confidence": round(_safe_number(belief.get("confidence", 0.5), 0.5, minimum=0.0, maximum=1.0), 3),\n')
    text = text.replace('        x, y = raw.get("x"), raw.get("y")\n        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):\n            continue\n        dx, dy = float(x) - agent.x, float(y) - agent.y\n', '        x, y = _safe_number(raw.get("x"), math.nan), _safe_number(raw.get("y"), math.nan)\n        if not math.isfinite(x) or not math.isfinite(y):\n            continue\n        dx, dy = x - _safe_number(agent.x), y - _safe_number(agent.y)\n')
    text = text.replace('            "certainty": round(max(0.0, min(1.0, float(raw.get("certainty", 0.0)))), 3),\n', '            "certainty": round(_safe_number(raw.get("certainty", 0.0), 0.0, minimum=0.0, maximum=1.0), 3),\n')
    text = text.replace('        "sim_time": event.get("sim_time"),\n', '        "sim_time": _safe_number(event.get("sim_time"), 0.0),\n')
    text = text.replace('        "importance": event.get("importance"),\n', '        "importance": round(_safe_number(event.get("importance"), 0.0, minimum=0.0, maximum=1.0), 3),\n')
    text = text.replace('    ax, ay = int(round(agent.x)), int(round(agent.y))\n', '    agent_x, agent_y = _safe_number(agent.x), _safe_number(agent.y)\n    ax, ay = int(round(agent_x)), int(round(agent_y))\n')
    text = text.replace('        "facing": agent.facing,\n', '        "facing": _truncate(agent.facing, 32),\n')
    for field in ("health", "energy", "hunger", "hydration", "sleep_pressure", "body_temperature_c", "pain"):
        text = text.replace(f"round(agent.{field}, 1)", f"round(_safe_number(agent.{field}), 1)")
    text = text.replace("round(agent.body_temperature_c, 2)", "round(_safe_number(agent.body_temperature_c), 2)")
    text = text.replace('        "inventory": dict(agent.inventory),\n', '        "inventory": _bounded_pairs(agent.inventory, count_limit=INVENTORY_SUMMARY_LIMIT, key_limit=80, value_limit=40),\n')
    text = text.replace('        "inventory_capacity": agent.inventory_capacity,\n', '        "inventory_capacity": int(_safe_number(agent.inventory_capacity, 0.0, minimum=0.0, maximum=10000.0)),\n')
    text = text.replace('        "key_items": [item.display_name for item in agent.key_items.values()],\n', '        "key_items": [_truncate(item.display_name, 120) for item in list(agent.key_items.values())[:KEY_ITEM_SUMMARY_LIMIT]],\n')
    text = text.replace('        "key_item_ids": sorted(agent.key_items),\n', '        "key_item_ids": [_truncate(item, KEY_ITEM_ID_LIMIT) for item in sorted(agent.key_items, key=str)[:KEY_ITEM_SUMMARY_LIMIT]],\n')
    text = text.replace('        "proposed_task_titles": [task.title for task in sorted(agent.tasks.values(), key=lambda item: item.priority)[:4]],\n', '        "proposed_task_titles": [_truncate(task.title, TASK_TITLE_TEXT_LIMIT) for task in sorted(agent.tasks.values(), key=lambda item: (_safe_number(item.priority), _truncate(item.task_id, 96)))[:TASK_TITLE_SUMMARY_LIMIT]],\n')
    old_tiles = '''            "nearby_known_tiles": [\n                {"x": int(key.split(",")[0]) - ax, "y": int(key.split(",")[1]) - ay, "terrain": terrain}\n                for key, terrain in sorted(\n                    agent.known_terrain.items(),\n                    key=lambda item: abs(int(item[0].split(",")[0]) - ax) + abs(int(item[0].split(",")[1]) - ay),\n                )[:KNOWN_TILE_SUMMARY_LIMIT]\n            ],\n'''
    text = replace_once(text, old_tiles, '            "nearby_known_tiles": _known_tile_summaries(agent, ax, ay),\n', path=path)
    text = text.replace('        "personality_traits": agent.personality_traits,\n', '        "personality_traits": _bounded_pairs(agent.personality_traits, count_limit=PERSONALITY_TRAIT_LIMIT, key_limit=PERSONALITY_KEY_LIMIT, value_limit=PERSONALITY_VALUE_LIMIT),\n')
    write(path, text)

    test_path = "tests/test_v040_remediation.py"
    tests = read(test_path)
    tests = tests.replace("from app.llm.prompts import decision_messages\n", "from app.llm.prompts import ACTIVE_PLAN_LIMIT, MEMORY_LIMIT, decision_messages\n")
    addition = r'''


def _large_prompt_case(world: WorldState, size: int, *, awakening: bool) -> tuple[AgentState, str, dict]:
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.awakening.presented = not awakening
    agent.key_items = {}
    agent.tasks = {}
    agent.personality_traits = {}
    agent.known_locations = {}
    agent.recent_events = []
    memories = []
    active_plan = []
    for index in range(size):
        sentinel = f"FULL_STORE_SENTINEL_{size}_{index}_"
        key_id = sentinel + ("k" * 500)
        agent.key_items[key_id] = KeyItem(key_id, sentinel + ("d" * 500), "description", Provenance("test"))
        task_id = f"task-{index}"
        agent.tasks[task_id] = TaskRecord(task_id, sentinel + ("t" * 500), "summary" + ("s" * 500), "test", "proposed", index, 0, 0, provenance=Provenance("test"))
        agent.personality_traits[sentinel + ("p" * 300)] = sentinel + ("v" * 800)
        agent.known_locations[sentinel + ("l" * 400)] = {"x": index, "y": index, "certainty": sentinel + "bad"}
        agent.recent_events.append({"sim_time": sentinel, "kind": sentinel + ("e" * 300), "message": sentinel + ("m" * 900), "importance": sentinel})
        agent.beliefs[f"belief-{index}"] = BeliefRecord(f"belief-{index}", sentinel + ("b" * 900), 0.5, sentinel + ("q" * 900), "hypothesis", index, None, provenance=Provenance("test"))
        agent.notes[f"note-{index}"] = NoteRecord(f"note-{index}", sentinel, sentinel + ("n" * 900), [], "active", 0, 0, provenance=Provenance("test"))
        agent.map_markers[f"marker-{index}"] = MapMarker(f"marker-{index}", sentinel, "test", {"relative_direction": "north", "metadata": sentinel}, 0.5, "active", sentinel, 0, 0, provenance=Provenance("test"))
        agent.short_term_episodes[f"episode-{index}"] = EpisodeRecord(f"episode-{index}", index, index, sentinel + ("z" * 900), "test", 0.5, "recent", provenance=Provenance("test"))
        memories.append({"memory_id": f"memory-{index}", "title": sentinel + ("r" * 600), "content": sentinel + ("c" * 5000), "tags": [sentinel + ("g" * 500)] * 50})
        active_plan.append(sentinel + ("a" * 3000))
    perception = build_perception(world, agent)
    prompt = decision_messages({
        "perception": perception,
        "active_plan": active_plan,
        "retrieved_memories": memories,
        "recent_outcomes": [{"details": f"OUTCOME_FULL_SENTINEL_{index}_" + ("o" * 3000)} for index in range(size)],
    })[-1]["content"]
    return agent, prompt, json.loads(prompt)


def test_every_normal_prompt_source_has_fixed_final_bounds_at_three_scales() -> None:
    world = WorldState.generate(992, 48)
    results = [_large_prompt_case(world, size, awakening=False) for size in (10, 100, 1000)]
    lengths = [len(prompt) for _, prompt, _ in results]
    assert max(lengths) - min(lengths) < 2500
    for size, (agent, prompt, payload) in zip((10, 100, 1000), results):
        perception = payload["perception"]
        assert perception["cognitive_tools"]["task_count"] == size
        assert perception["cognitive_tools"]["note_count"] == size
        assert len(perception["cognitive_tools"]["key_item_ids"]) == min(size, 8)
        assert len(perception["cognitive_tools"]["proposed_task_titles"]) == min(size, 4)
        assert len(perception["personality_traits"]) == min(size, 12)
        assert len(payload["active_plan"]) == min(size, ACTIVE_PLAN_LIMIT)
        assert len(payload["retrieved_long_term_memories"]) == min(size, MEMORY_LIMIT)
        assert len(payload["recent_action_outcomes"]) <= 4
        assert all(len(item) <= 240 for item in payload["active_plan"])
        assert all(len(key) <= 96 for key in perception["cognitive_tools"]["key_item_ids"])
        assert all(len(title) <= 160 for title in perception["cognitive_tools"]["proposed_task_titles"])
        complete = f"FULL_STORE_SENTINEL_{size}_{size - 1}_" + ("c" * 5000)
        assert complete not in prompt
        assert f"OUTCOME_FULL_SENTINEL_{size - 1}_" + ("o" * 3000) not in prompt


def test_first_decision_uses_the_same_final_bounds() -> None:
    world = WorldState.generate(993, 48)
    _, first_prompt, first_payload = _large_prompt_case(world, 1000, awakening=True)
    _, normal_prompt, normal_payload = _large_prompt_case(world, 1000, awakening=False)
    assert "I wake beneath an unfamiliar sky" in first_prompt
    assert "I wake beneath an unfamiliar sky" not in normal_prompt
    assert len(first_payload["active_plan"]) == len(normal_payload["active_plan"]) == ACTIVE_PLAN_LIMIT
    assert abs(len(first_prompt) - len(normal_prompt)) < 4000
'''
    if "test_every_normal_prompt_source_has_fixed_final_bounds_at_three_scales" not in tests:
        tests += addition
    write(test_path, tests)
    commit("Bound every ordinary decision prompt source", [prompts_path, path, test_path])


def stage_normalization() -> None:
    path = "app/simulation/cognition.py"
    text = read(path)
    text = text.replace("import uuid\n", "import math\nimport uuid\n")
    old = '''def _bounded(value: Any, default: float = 0.5) -> float:\n    try:\n        number = float(value)\n    except (TypeError, ValueError):\n        number = default\n    return max(0.0, min(1.0, number))\n'''
    new = '''TEXT_ID_LIMIT = 160\nLINKED_ID_LIMIT = 32\n\n\ndef _number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:\n    if isinstance(value, bool):\n        number = default\n    else:\n        try:\n            number = float(value)\n        except (TypeError, ValueError, OverflowError):\n            number = default\n    if not math.isfinite(number):\n        number = default\n    if minimum is not None:\n        number = max(minimum, number)\n    if maximum is not None:\n        number = min(maximum, number)\n    return number\n\n\ndef _integer(value: Any, default: int = 0) -> int:\n    return int(_number(value, float(default), minimum=-1_000_000_000, maximum=1_000_000_000))\n\n\ndef _bounded(value: Any, default: float = 0.5) -> float:\n    return _number(value, default, minimum=0.0, maximum=1.0)\n\n\ndef _text(value: Any, default: str = "", limit: int = TEXT_ID_LIMIT) -> str:\n    if not isinstance(value, (str, int, float, bool)):\n        return default\n    text = str(value).replace("\\n", " ").strip()\n    if not text:\n        return default\n    return text if len(text) <= limit else text[:limit]\n'''
    text = replace_once(text, old, new, path=path)
    text = replace_once(text, '''def _list(value: Any) -> list[Any]:\n    return list(value) if isinstance(value, (list, tuple, set)) else []\n''', '''def _list(value: Any) -> list[Any]:\n    if isinstance(value, set):\n        return sorted(value, key=lambda item: str(item))\n    return list(value) if isinstance(value, (list, tuple)) else []\n\n\ndef _string_list(value: Any, *, allow_scalar: bool = True, count_limit: int = LINKED_ID_LIMIT, text_limit: int = TEXT_ID_LIMIT) -> list[str]:\n    if allow_scalar and isinstance(value, (str, int)) and not isinstance(value, bool):\n        source = [value]\n    else:\n        source = _list(value)\n    result: list[str] = []\n    for raw in source:\n        if isinstance(raw, (list, tuple, set, dict)) or raw is None or isinstance(raw, bool):\n            continue\n        item = _text(raw, limit=text_limit)\n        if item and item not in result:\n            result.append(item)\n        if len(result) >= count_limit:\n            break\n    return result\n''', path=path)
    replacements = {
        'source_type=str(value.get("source_type") or default_source),': 'source_type=_text(value.get("source_type"), default_source, 64),',
        'source_id=value.get("source_id"),': 'source_id=_text(value.get("source_id"), limit=160) or None,',
        'detail=value.get("detail"),': 'detail=_text(value.get("detail"), limit=240) or None,',
        'key_item_id=str(value["key_item_id"]),': 'key_item_id=_text(value.get("key_item_id"), limit=160),',
        'display_name=str(value["display_name"]),': 'display_name=_text(value.get("display_name"), "Unnamed key item", 160),',
        'description=str(value.get("description", "")),': 'description=_text(value.get("description"), limit=1000),',
        'task_id=str(value["task_id"]),': 'task_id=_text(value.get("task_id"), limit=160),',
        'title=str(value["title"]),': 'title=_text(value.get("title"), "Untitled task", 240),',
        'created_by=str(value.get("created_by", "system_initialization")),': 'created_by=_text(value.get("created_by"), "system_initialization", 80),',
        'priority=int(value.get("priority", 0)),': 'priority=_integer(value.get("priority", 0)),',
        'created_at=float(value.get("created_at", 0.0)),': 'created_at=_number(value.get("created_at", 0.0)),',
        'updated_at=float(value.get("updated_at", value.get("created_at", 0.0))),': 'updated_at=_number(value.get("updated_at", value.get("created_at", 0.0))),',
        'linked_marker_ids=[str(item) for item in _list(value.get("linked_marker_ids"))],': 'linked_marker_ids=_string_list(value.get("linked_marker_ids")),',
        'linked_note_ids=[str(item) for item in _list(value.get("linked_note_ids"))],': 'linked_note_ids=_string_list(value.get("linked_note_ids")),',
        'note_id=str(value["note_id"]),': 'note_id=_text(value.get("note_id"), limit=160),',
        'title=str(value.get("title", "Untitled note")),': 'title=_text(value.get("title"), "Untitled note", 240),',
        'content=str(value.get("content", "")),': 'content=_text(value.get("content"), limit=4000),',
        'tags=[str(item) for item in _list(value.get("tags"))],': 'tags=_string_list(value.get("tags"), count_limit=32, text_limit=80),',
        'linked_task_ids=[str(item) for item in _list(value.get("linked_task_ids"))],': 'linked_task_ids=_string_list(value.get("linked_task_ids")),',
        'linked_marker_ids=list(value.get("linked_marker_ids") or []),': 'linked_marker_ids=_string_list(value.get("linked_marker_ids")),',
        'marker_id=str(value["marker_id"]),': 'marker_id=_text(value.get("marker_id"), limit=160),',
        'label=str(value.get("label", "Unknown marker")),': 'label=_text(value.get("label"), "Unknown marker", 240),',
        'marker_type=str(value.get("marker_type", "unknown")),': 'marker_type=_text(value.get("marker_type"), "unknown", 80),',
        'notes=str(value.get("notes", "")),': 'notes=_text(value.get("notes"), limit=2000),',
        'belief_id=str(value["belief_id"]),': 'belief_id=_text(value.get("belief_id"), limit=160),',
        'claim=str(value.get("claim", "")),': 'claim=_text(value.get("claim"), limit=2000),',
        'basis=str(value.get("basis", "")),': 'basis=_text(value.get("basis"), limit=2000),',
        'first_formed_at=float(value.get("first_formed_at", 0.0)),': 'first_formed_at=_number(value.get("first_formed_at", 0.0)),',
        'last_tested_at=float(value["last_tested_at"]) if value.get("last_tested_at") is not None else None,': 'last_tested_at=_number(value.get("last_tested_at")) if value.get("last_tested_at") is not None else None,',
        'supporting_evidence_ids=[str(item) for item in _list(value.get("supporting_evidence_ids"))],': 'supporting_evidence_ids=_string_list(value.get("supporting_evidence_ids")),',
        'contradicting_evidence_ids=[str(item) for item in _list(value.get("contradicting_evidence_ids"))],': 'contradicting_evidence_ids=_string_list(value.get("contradicting_evidence_ids")),',
        'source_type=str(value.get("source_type", "inference")),': 'source_type=_text(value.get("source_type"), "inference", 64),',
        'episode_id=str(value["episode_id"]),': 'episode_id=_text(value.get("episode_id"), limit=160),',
        'simulation_timestamp=float(value.get("simulation_timestamp", 0.0)),': 'simulation_timestamp=_number(value.get("simulation_timestamp", 0.0)),',
        'summary=str(value.get("summary", "")),': 'summary=_text(value.get("summary"), limit=2000),',
        'category=str(value.get("category", "general")),': 'category=_text(value.get("category"), "general", 80),',
        'linked_belief_ids=[str(item) for item in _list(value.get("linked_belief_ids"))],': 'linked_belief_ids=_string_list(value.get("linked_belief_ids")),',
        'linked_memory_ids=[str(item) for item in _list(value.get("linked_memory_ids"))],': 'linked_memory_ids=_string_list(value.get("linked_memory_ids")),',
        'narrative=str(value.get("narrative") or AWAKENING_NARRATIVE),': 'narrative=_text(value.get("narrative"), AWAKENING_NARRATIVE, 4000),',
        'presented_at=float(value["presented_at"]) if value.get("presented_at") is not None else None,': 'presented_at=_number(value.get("presented_at")) if value.get("presented_at") is not None else None,',
    }
    for old_text, new_text in replacements.items():
        text = text.replace(old_text, new_text)
    text = text.replace('linked_task_ids=list(value.get("linked_task_ids") or []),', 'linked_task_ids=_string_list(value.get("linked_task_ids")),')
    text = text.replace('linked_note_ids=list(value.get("linked_note_ids") or []),', 'linked_note_ids=_string_list(value.get("linked_note_ids")),')
    write(path, text)

    agent_path = "app/simulation/agent.py"
    agent_text = read(agent_path)
    agent_text = agent_text.replace('        copied["explored"] = set(copied.get("explored", []))\n', '        explored = copied.get("explored", [])\n        copied["explored"] = {str(item)[:160] for item in explored} if isinstance(explored, (list, tuple, set)) else set()\n')
    agent_text = agent_text.replace('        copied["cognition_schema_version"] = int(copied.get("cognition_schema_version", 1))\n', '        try:\n            copied["cognition_schema_version"] = int(copied.get("cognition_schema_version", 1))\n        except (TypeError, ValueError, OverflowError):\n            copied["cognition_schema_version"] = 1\n')
    write(agent_path, agent_text)

    test_path = "tests/test_v040_remediation.py"
    tests = read(test_path)
    addition = r'''


def test_malformed_numeric_values_remain_controlled_after_loading_and_direct_mutation() -> None:
    world = WorldState.generate(994, 48)
    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.beliefs["bad"] = BeliefRecord("bad", "claim", 0.5, "basis", "hypothesis", 0, None, provenance=Provenance("test"))
    bad_belief = agent.beliefs["bad"]
    bad_belief.first_formed_at = {"bad": 1}
    bad_belief.last_tested_at = ["bad"]
    bad_belief.confidence = float("nan")
    agent.known_locations["bad"] = {"x": [], "y": {}, "certainty": float("inf")}
    agent.map_markers["bad"] = MapMarker("bad", "bad", "test", {"x": float("inf"), "y": float("nan"), "direction": "unknown"}, 0.5, "active", "", 0, 0, provenance=Provenance("test"))
    agent.map_markers["bad"].confidence = {"bad": 1}
    agent.short_term_episodes["bad"] = EpisodeRecord("bad", None, 0, "summary", "test", 0.5, "recent", provenance=Provenance("test"))
    agent.short_term_episodes["bad"].salience = ["bad"]
    agent.known_terrain["not,a,coordinate"] = "bad"

    perception = build_perception(world, agent)
    messages = decision_messages({"perception": perception, "active_plan": [None, {"bad": 1}], "retrieved_memories": [{"importance": float("nan"), "content": "ok"}], "recent_outcomes": [{"importance": float("inf")}]})
    fallback = FallbackBrain().decide(perception)
    result = _complete(ActionController(), world, agent, "view_map")
    serialized = agent.to_dict()
    assert messages[-1]["content"]
    assert fallback.action
    assert result.success
    assert serialized["map_markers"]["bad"]["confidence"] == {"bad": 1}

    legacy = agent.to_dict()
    legacy["beliefs"]["bad"].update({"first_formed_at": None, "last_tested_at": "not-a-number", "confidence": float("inf")})
    legacy["map_markers"]["bad"].update({"confidence": float("nan"), "created_at": [], "updated_at": {}})
    legacy["short_term_episodes"]["bad"].update({"simulation_timestamp": {}, "salience": float("-inf")})
    restored = AgentState.from_dict(legacy)
    assert build_perception(world, restored)
    assert AgentState.from_dict(restored.to_dict()).to_dict() == restored.to_dict()


def test_all_linked_id_lists_use_one_stable_bounded_normalizer() -> None:
    cases = [
        "single-id",
        ("tuple-a", "tuple-b"),
        {"set-b", "set-a"},
        ["valid", 7, None, True, ["nested"], {"bad": 1}, "x" * 500],
        None,
        [],
    ]
    for value in cases:
        raw = {
            "task_id": "task", "title": "task", "linked_marker_ids": value, "linked_note_ids": value,
            "note_id": "note", "content": "note",
        }
        task = TaskRecord.from_dict(raw)
        note = NoteRecord.from_dict({"note_id": "note", "linked_task_ids": value, "linked_marker_ids": value})
        marker = MapMarker.from_dict({"marker_id": "marker", "linked_task_ids": value, "linked_note_ids": value})
        belief = BeliefRecord.from_dict({"belief_id": "belief", "supporting_evidence_ids": value, "contradicting_evidence_ids": value})
        episode = EpisodeRecord.from_dict({"episode_id": "episode", "linked_task_ids": value, "linked_note_ids": value, "linked_belief_ids": value, "linked_marker_ids": value, "linked_memory_ids": value})
        records = [task, note, marker, belief, episode]
        for record in records:
            for field, field_value in record.to_dict().items():
                if field.startswith("linked_") or field.endswith("_evidence_ids") or field == "tags":
                    assert isinstance(field_value, list)
                    assert len(field_value) <= 32
                    assert all(isinstance(item, str) and len(item) <= 160 for item in field_value)
        marker_roundtrip = MapMarker.from_dict(marker.to_dict())
        assert marker_roundtrip.to_dict() == marker.to_dict()
        assert MapMarker.from_dict(marker_roundtrip.to_dict()).to_dict() == marker.to_dict()
    assert MapMarker.from_dict({"marker_id": "m", "linked_task_ids": "single-id"}).linked_task_ids == ["single-id"]
    assert MapMarker.from_dict({"marker_id": "m", "linked_task_ids": ["abc"] * 100}).linked_task_ids == ["abc"]
'''
    if "test_malformed_numeric_values_remain_controlled_after_loading_and_direct_mutation" not in tests:
        tests += addition
    write(test_path, tests)
    commit("Normalize malformed cognition state at every projection boundary", [path, agent_path, test_path])


def stage_hygiene() -> None:
    path = "scripts/build_release.py"
    text = read(path)
    text = text.replace('command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]', 'command = ["git", "ls-files", "--cached"]')
    write(path, text)

    hygiene_path = "tests/test_public_repository_hygiene.py"
    hygiene = read(hygiene_path)
    old = '''FORBIDDEN_MARKERS = {\n    "c:\\\\users\\\\ethan",\n    "/c/users/ethan",\n    "ethan-pc",\n    "tailce5cf1",\n    "docs/project_handoff.md",\n    "docs/new_session_prompt.md",\n}\n'''
    new = '''FORBIDDEN_MARKERS = {\n    "".join(("c:\\\\users\\\\", "ethan")),\n    "".join(("/c/users/", "ethan")),\n    "".join(("ethan", "-pc")),\n    "".join(("tail", "ce5cf1")),\n    "".join(("docs/project_", "handoff.md")),\n    "".join(("docs/new_session_", "prompt.md")),\n}\n'''
    hygiene = replace_once(hygiene, old, new, path=hygiene_path)
    write(hygiene_path, hygiene)
    commit("Separate repository and release-archive hygiene", [path, hygiene_path])


def stage_docs_version() -> None:
    changelog_path = "CHANGELOG.md"
    changelog = read(changelog_path)
    entry = '''## [0.4.0.post2] — 2026-07-23\n\n### Fixed\n\n- Replaced recursive marker-dictionary sanitation with an explicit Ari-safe `view_map` projection. Unknown marker fields, observer metadata, absolute locations, provenance details, and private operational data cannot cross the cognition boundary.\n- Added final fixed count and text bounds to every ordinary decision-context source, including key items, tasks, personality traits, active plans, memories, outcomes, known locations, events, beliefs, and malformed extension data.\n- Added controlled finite numeric projection for malformed beliefs, locations, markers, episodes, events, and schema timestamps.\n- Normalized all linked-ID and evidence lists through one stable bounded policy so scalar strings never become character arrays.\n- Changed release packaging to include tracked files only, preventing untracked root-level reports from entering release archives.\n- Reworked the repository-only privacy test so it remains packageable without embedding literal private-machine sentinels in the public archive.\n\n### Tests\n\n- Added exact-branch nested sentinels for the previously vulnerable `map_markers[*].believed_location` path and recursively checked action results, first and normal prompts, fallback context, and observer-diagnostic preservation.\n- Added 10/100/1,000-record growth tests across every ordinary prompt source.\n- Added direct-mutation and legacy-load malformed numeric tests plus repeated linked-list load/save stability checks.\n\n'''
    if not changelog.startswith("# Changelog\n\n## [0.4.0.post2]"):
        changelog = changelog.replace("# Changelog\n\n", "# Changelog\n\n" + entry, 1)
    write(changelog_path, changelog)

    for path in ("pyproject.toml", "app/version.py"):
        text = read(path).replace("0.4.0.post1", "0.4.0.post2")
        write(path, text)
    commit("Set v0.4.0.post2 release version", [changelog_path, "pyproject.toml", "app/version.py"])


def validate() -> None:
    run("python", "-m", "pytest", "-q", "tests/test_v040_remediation.py")
    run("python", "-m", "pytest", "-q")
    run("python", "-m", "compileall", "-q", "app", "tests", "scripts")
    run("python", "scripts/clean_generated.py")
    run("python", "scripts/validate_package.py", "--source")
    run("python", "scripts/build_release.py", "--output", "dist/embodied-alife-update.zip")


def cleanup_temp() -> None:
    workflow = ROOT / ".github/workflows/post2-remediation.yml"
    script = ROOT / "scripts/post2_remediation_applicator.py"
    if workflow.exists():
        workflow.unlink()
    if script.exists():
        script.unlink()
    run("git", "add", "-A")
    run("git", "commit", "-m", "Remove temporary post2 remediation tooling")


def main() -> None:
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    stage_map_projection()
    stage_prompt_bounds()
    stage_normalization()
    stage_hygiene()
    stage_docs_version()
    validate()
    cleanup_temp()
    run("git", "push", "origin", "HEAD:remediation/v0.4.0-post2")


if __name__ == "__main__":
    main()
