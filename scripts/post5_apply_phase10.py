from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str, label: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


patch(
    "app/serialization.py",
    '''    """Convert a scalar to a bounded finite float without treating booleans as numbers."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
''',
    '''    """Convert an explicitly supported scalar to a bounded finite float.

    Booleans, bytes, containers, and arbitrary objects are rejected even when their
    Python type implements numeric conversion. Numeric strings remain supported.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        candidate: int | float | str = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return default
    else:
        return default
    try:
        number = float(candidate)
''',
    "finite scalar policy",
)
patch(
    "app/simulation/cognition.py",
    '''def starter_key_items() -> dict[str, KeyItem]:
    source = Provenance("system_initialization", detail="v0.4.0 starter kit")
    return {
        "blank_field_map": KeyItem("blank_field_map", "Blank Field Map", "A blank field map for recording Ari's own knowledge.", source),
        "task_journal": KeyItem("task_journal", "Task Journal", "A journal containing broad survival reminders.", source),
        "field_notebook": KeyItem("field_notebook", "Field Notebook", "A notebook for Ari's own observations and notes.", source),
    }
''',
    '''def starter_key_items() -> dict[str, KeyItem]:
    return {
        "blank_field_map": KeyItem(
            "blank_field_map", "Blank Field Map", "A blank field map for recording Ari's own knowledge.",
            Provenance("system_initialization", detail="v0.4.0 starter kit"),
        ),
        "task_journal": KeyItem(
            "task_journal", "Task Journal", "A journal containing broad survival reminders.",
            Provenance("system_initialization", detail="v0.4.0 starter kit"),
        ),
        "field_notebook": KeyItem(
            "field_notebook", "Field Notebook", "A notebook for Ari's own observations and notes.",
            Provenance("system_initialization", detail="v0.4.0 starter kit"),
        ),
    }
''',
    "independent starter provenance",
)
patch(
    "tests/test_diagnostics_v2.py",
    '''    assert runtime["database_path"] == str(engine.database.path)
    assert runtime["memory_path"] == str(engine.vault.root)
''',
    '''    assert runtime["database_path"] == "<local-path-omitted>"
    assert runtime["memory_path"] == "<local-path-omitted>"
''',
    "diagnostic path privacy expectation",
)

path = ROOT / "tests/test_v040_cognitive_foundations.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from app.simulation.perception import build_perception\n",
    '''from app.simulation.integrity import attach_key, seal_deterministic_starters, seal_knowledge, seal_record
from app.simulation.perception import build_perception
''',
    1,
)
text = text.replace(
    '''def _decision(action: str, *, target_id: str | None = None) -> ActionDecision:
''',
    '''KEY = b"cognitive-foundations-key".ljust(32, b"!")


def _prepare(agent: AgentState) -> None:
    attach_key(agent, KEY)
    seal_deterministic_starters(agent, KEY)


def _decision(action: str, *, target_id: str | None = None) -> ActionDecision:
''',
    1,
)
text = text.replace(
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.notes["n1"] = NoteRecord''',
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare(agent)
    agent.notes["n1"] = NoteRecord''',
    1,
)
text = text.replace(
    '''    agent.map_markers["m1"] = MapMarker("m1", "Possible water", "water", {"relative": "west"}, 0.4, "active", "uncertain", 0, 0, provenance=Provenance("inference"))
    controller = ActionController()
    agent.known_terrain["41,7"] = "known meadow"
''',
    '''    agent.map_markers["m1"] = MapMarker("m1", "Possible water", "water", {"relative": "west"}, 0.4, "active", "uncertain", 0, 0, provenance=Provenance("inference"))
    assert seal_record("note", agent.notes["n1"], KEY, "validated_model_response", source_type="agent", source_ref="test-note")
    assert seal_record("marker", agent.map_markers["m1"], KEY, "validated_model_response", source_type="inference", source_ref="test-marker")
    controller = ActionController()
    agent.known_terrain["41,7"] = "known meadow"
    assert seal_knowledge(agent, "terrain", "41,7", "known meadow", "validated_perception", source_ref="test-terrain")
''',
    1,
)
text = text.replace(
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    for index in range(100):
        agent.notes[str(index)] = NoteRecord(str(index), f"Note {index}", "x" * 500, [], "active", 0, 0, provenance=Provenance("agent"))
''',
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare(agent)
    for index in range(100):
        agent.notes[str(index)] = NoteRecord(str(index), f"Note {index}", "x" * 500, [], "active", 0, 0, provenance=Provenance("agent"))
        assert seal_record("note", agent.notes[str(index)], KEY, "validated_model_response", source_type="agent", source_ref=f"note:{index}")
''',
    1,
)
path.write_text(text, encoding="utf-8", newline="\n")
print("post5 phase10 applied")
