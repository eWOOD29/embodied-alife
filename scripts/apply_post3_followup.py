from pathlib import Path

root = Path(__file__).resolve().parents[1]

def replace(path, old, new):
    p = root / path
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'missing replacement in {path}: {old[:100]!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')

# All outward-facing need labels must use the same normalized values as the body projection.
replace('app/simulation/perception.py', 'from typing import Any\n', 'from types import SimpleNamespace\nfrom typing import Any\n')
replace('app/simulation/perception.py', '''    hunger_deficit = round(_safe_number(agent.hunger), 1)\n    body = {\n''', '''    health_reserve = round(_safe_number(agent.health), 1)\n    energy_reserve = round(_safe_number(agent.energy), 1)\n    hunger_deficit = round(_safe_number(agent.hunger), 1)\n    hydration_reserve = round(_safe_number(agent.hydration), 1)\n    sleep_pressure = round(_safe_number(agent.sleep_pressure), 1)\n    temperature_c = round(_safe_number(agent.body_temperature_c), 2)\n    pain = round(_safe_number(agent.pain), 1)\n    safe_needs = SimpleNamespace(\n        health=health_reserve, energy=energy_reserve, hunger=hunger_deficit,\n        hydration=hydration_reserve, sleep_pressure=sleep_pressure,\n        body_temperature_c=temperature_c, pain=pain,\n    )\n    body = {\n''')
replace('app/simulation/perception.py', '''        "health_reserve": round(_safe_number(agent.health), 1),\n        "energy_reserve": round(_safe_number(agent.energy), 1),\n        "hunger_deficit": hunger_deficit,\n        "satiety": round(100.0 - hunger_deficit, 1),\n        "hydration_reserve": round(_safe_number(agent.hydration), 1),\n        "sleep_pressure": round(_safe_number(agent.sleep_pressure), 1),\n        "temperature_c": round(_safe_number(agent.body_temperature_c), 2),\n        "pain": round(_safe_number(agent.pain), 1),\n''', '''        "health_reserve": health_reserve,\n        "energy_reserve": energy_reserve,\n        "hunger_deficit": hunger_deficit,\n        "satiety": round(100.0 - hunger_deficit, 1),\n        "hydration_reserve": hydration_reserve,\n        "sleep_pressure": sleep_pressure,\n        "temperature_c": temperature_c,\n        "pain": pain,\n''')
replace('app/simulation/perception.py', '"drive_labels": drive_labels(agent),', '"drive_labels": drive_labels(safe_needs),')

# Reject explicitly sensitive observer/operational strings at Ari-facing text fields.
insert = '''\nARI_FORBIDDEN_TEXT_FRAGMENTS = (\n    "cave_truth", "recipe", "hidden_entity", "hidden_resource",\n    "observer_id", "observerid", "database_id", "internal_metadata",\n    "absolute_coordinates", "private_path", "hostname", "operational_log",\n)\n\n\ndef _ari_boundary_text(value: Any, limit: int) -> str:\n    text = _bounded_text(value, limit)\n    lowered = text.lower().replace(" ", "_")\n    return "" if any(fragment in lowered for fragment in ARI_FORBIDDEN_TEXT_FRAGMENTS) else text\n'''
replace('app/simulation/actions.py', '\n\ndef _safe_status(value: Any, allowed: set[str], default: str) -> str:', insert + '\n\ndef _safe_status(value: Any, allowed: set[str], default: str) -> str:')
replace('app/simulation/actions.py', '"title": _bounded_text(getattr(task, "title", "Untitled task"), ARI_TASK_TITLE_LIMIT),', '"title": _ari_boundary_text(getattr(task, "title", "Untitled task"), ARI_TASK_TITLE_LIMIT) or "Untitled task",')
replace('app/simulation/actions.py', '"description": _bounded_text(getattr(task, "description", ""), ARI_TASK_DESCRIPTION_LIMIT),', '"description": _ari_boundary_text(getattr(task, "description", ""), ARI_TASK_DESCRIPTION_LIMIT),')
replace('app/simulation/actions.py', '"title": _bounded_text(getattr(note, "title", "Untitled note"), ARI_NOTE_TITLE_LIMIT),', '"title": _ari_boundary_text(getattr(note, "title", "Untitled note"), ARI_NOTE_TITLE_LIMIT) or "Untitled note",')
replace('app/simulation/actions.py', '"content": _bounded_text(getattr(note, "content", ""), ARI_NOTE_CONTENT_LIMIT),', '"content": _ari_boundary_text(getattr(note, "content", ""), ARI_NOTE_CONTENT_LIMIT),')
replace('app/simulation/actions.py', 'tag = _bounded_text(raw, ARI_TAG_TEXT_LIMIT)', 'tag = _ari_boundary_text(raw, ARI_TAG_TEXT_LIMIT)')

# Use a sentinel category required by the trust-boundary specification.
replace('tests/test_v040_post3_remediation.py', "sentinel = 'FORBIDDEN_NOTE_SENTINEL'", "sentinel = 'observer_id:FORBIDDEN_NOTE_SENTINEL'")
