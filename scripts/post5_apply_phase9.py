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


# Malformed entries must be skipped, not terminate loading of later valid records.
patch(
    "app/simulation/agent.py",
    '''    for index, (key, raw) in enumerate(value.items()):
        if index >= 10000 or not isinstance(raw, dict):
            break
''',
    '''    for index, (key, raw) in enumerate(value.items()):
        if index >= 10000:
            break
        if not isinstance(raw, dict):
            continue
''',
    "agent record loader",
)
patch(
    "app/simulation/world.py",
    '''            for index, (raw_key, raw_value) in enumerate(value.items()):
                if index >= 10000 or not isinstance(raw_key, str) or not isinstance(raw_value, dict):
                    if index >= 10000:
                        break
                    continue
''',
    '''            for index, (raw_key, raw_value) in enumerate(value.items()):
                if index >= 10000:
                    break
                if not isinstance(raw_key, str) or not isinstance(raw_value, dict):
                    continue
''',
    "world record loader",
)

path = ROOT / "tests/test_v040_remediation.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from app.simulation.perception import BELIEF_SUMMARY_LIMIT, KNOWN_TILE_SUMMARY_LIMIT, build_perception\n",
    '''from app.simulation.integrity import attach_key, seal_knowledge, seal_record
from app.simulation.perception import BELIEF_SUMMARY_LIMIT, KNOWN_TILE_SUMMARY_LIMIT, build_perception
''',
    1,
)
text = text.replace(
    '''def _decision(action: str) -> ActionDecision:
''',
    '''KEY = b"v040-remediation-test-key".ljust(32, b"!")


def _prepare(agent: AgentState) -> None:
    attach_key(agent, KEY)


def _seal(family: str, record, *, path: str = "validated_model_response", source: str = "inference", reference: str = "v040-test") -> None:
    assert seal_record(family, record, KEY, path, source_type=source, source_ref=reference)


def _decision(action: str) -> ActionDecision:
''',
    1,
)
text = text.replace(
    '''def _serialized_prompt(world: WorldState, agent: AgentState) -> str:
    perception = build_perception(world, agent)
''',
    '''def _serialized_prompt(world: WorldState, agent: AgentState) -> str:
    _prepare(agent)
    perception = build_perception(world, agent)
''',
    1,
)
text = text.replace(
    '''    agent.known_locations["HIDDEN_LOCATION_SENTINEL"] = {
''',
    '''    _prepare(agent)
    agent.known_locations["HIDDEN_LOCATION_SENTINEL"] = {
''',
    1,
)
text = text.replace(
    '''    agent.map_markers["marker"] = MapMarker(
        "marker", "subjective marker", "unknown", {"x": 41, "y": 7}, 0.4, "active", "Ari inference", 0, 0,
        provenance=Provenance("inference"),
    )
''',
    '''    agent.map_markers["marker"] = MapMarker(
        "marker", "subjective marker", "unknown", {"x": 41, "y": 7}, 0.4, "active", "Ari inference", 0, 0,
        provenance=Provenance("inference"),
    )
    assert seal_knowledge(agent, "terrain", "3,39", "known meadow", "validated_perception", source_ref="safe-terrain")
    _seal("marker", agent.map_markers["marker"], source="inference", reference="safe-marker")
''',
    1,
)
text = text.replace(
    '''    small = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    large = AgentState.from_dict(small.to_dict())
''',
    '''    small = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    large = AgentState.from_dict(small.to_dict())
    _prepare(small)
    _prepare(large)
''',
    1,
)
text = text.replace(
    '''        large.short_term_episodes[f"episode-{index}"] = EpisodeRecord(
            f"episode-{index}", index, index, f"EPISODE_SUMMARY_SENTINEL_{index}_" + ("e" * 900),
            "test", 0.5, "recent", provenance=Provenance("test"),
        )
''',
    '''        large.short_term_episodes[f"episode-{index}"] = EpisodeRecord(
            f"episode-{index}", index, index, f"EPISODE_SUMMARY_SENTINEL_{index}_" + ("e" * 900),
            "test", 0.5, "recent", provenance=Provenance("inference"),
        )
        large.beliefs[f"belief-{index:04d}"].provenance.source_type = "inference"
        large.notes[f"note-{index}"].provenance.source_type = "agent"
        large.tasks[f"task-{index}"].provenance.source_type = "inference"
        large.map_markers[f"marker-{index}"].provenance.source_type = "inference"
        _seal("belief", large.beliefs[f"belief-{index:04d}"], source="inference", reference=f"belief:{index}")
        _seal("note", large.notes[f"note-{index}"], source="agent", reference=f"note:{index}")
        _seal("task", large.tasks[f"task-{index}"], source="inference", reference=f"task:{index}")
        _seal("marker", large.map_markers[f"marker-{index}"], source="inference", reference=f"marker:{index}")
        _seal("episode", large.short_term_episodes[f"episode-{index}"], source="inference", reference=f"episode:{index}")
''',
    1,
)
text = text.replace(
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    full_claims = []
''',
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare(agent)
    full_claims = []
''',
    1,
)
text = text.replace(
    '''        agent.beliefs[f"b-{index}"] = claim
''',
    '''        agent.beliefs[f"b-{index}"] = claim
        belief = agent.beliefs[f"b-{index}"]
        belief.source_type = "inference"
        belief.provenance.source_type = "inference"
        _seal("belief", belief, source="inference", reference=f"first:{index}")
''',
    1,
)
text = text.replace(
    '''    agent = AgentState(x=17.0, y=23.0)
    forbidden_values = {
''',
    '''    agent = AgentState(x=17.0, y=23.0)
    _prepare(agent)
    forbidden_values = {
''',
    1,
)
text = text.replace(
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.awakening.presented = not awakening
''',
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare(agent)
    agent.awakening.presented = not awakening
''',
    1,
)
text = text.replace(
    '''        active_plan.append(sentinel + ("a" * 3000))
''',
    '''        active_plan.append(sentinel + ("a" * 3000))
        agent.key_items[key_id].provenance.source_type = "agent"
        agent.tasks[task_id].provenance.source_type = "inference"
        agent.beliefs[f"belief-{index}"].source_type = "inference"
        agent.beliefs[f"belief-{index}"].provenance.source_type = "inference"
        agent.notes[f"note-{index}"].provenance.source_type = "agent"
        agent.map_markers[f"marker-{index}"].provenance.source_type = "inference"
        agent.short_term_episodes[f"episode-{index}"].provenance.source_type = "inference"
        _seal("key_item", agent.key_items[key_id], source="agent", reference=f"key:{index}")
        _seal("task", agent.tasks[task_id], source="inference", reference=f"task:{index}")
        _seal("belief", agent.beliefs[f"belief-{index}"], source="inference", reference=f"belief:{index}")
        _seal("note", agent.notes[f"note-{index}"], source="agent", reference=f"note:{index}")
        _seal("marker", agent.map_markers[f"marker-{index}"], source="inference", reference=f"marker:{index}")
        _seal("episode", agent.short_term_episodes[f"episode-{index}"], source="inference", reference=f"episode:{index}")
''',
    1,
)
text = text.replace(
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    agent.beliefs["bad"] = BeliefRecord''',
    '''    agent = AgentState(x=float(world.spawn[0]), y=float(world.spawn[1]))
    _prepare(agent)
    agent.beliefs["bad"] = BeliefRecord''',
    1,
)
path.write_text(text, encoding="utf-8", newline="\n")
print("post5 phase9 applied")
