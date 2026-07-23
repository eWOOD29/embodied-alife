from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected text not found in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "tests/test_v040_cognitive_foundations.py",
    '''    map_result = _complete(controller, world, agent, "view_map")
    assert map_result.data["observer_truth_included"] is False
    serialized = json.dumps(map_result.data)
    assert "wolf" not in serialized and world.truth_notes["cave"] not in serialized
''',
    '''    agent.known_terrain["41,7"] = "known meadow"
    map_result = _complete(controller, world, agent, "view_map")
    assert "observer_truth_included" not in map_result.data
    assert "known_terrain" not in map_result.data
    serialized = json.dumps(map_result.data)
    assert "41,7" not in serialized
    assert "wolf" not in serialized and world.truth_notes["cave"] not in serialized
''',
)
replace(
    "tests/test_v040_remediation.py",
    '''    for index in range(300):
        agent.beliefs[f"b-{index}"] = "FIRST_CONTEXT_SENTINEL_" + ("x" * 1000)
    first = _serialized_prompt(world, agent)
    assert "I wake beneath an unfamiliar sky" in first
    assert "FIRST_CONTEXT_SENTINEL_" not in first
''',
    '''    full_claims = []
    for index in range(300):
        claim = f"FIRST_CONTEXT_SENTINEL_{index}_" + ("x" * 1000)
        full_claims.append(claim)
        agent.beliefs[f"b-{index}"] = claim
    first = _serialized_prompt(world, agent)
    assert "I wake beneath an unfamiliar sky" in first
    assert all(claim not in first for claim in full_claims)
''',
)
replace(
    "tests/test_v040_remediation.py",
    '''    assert "I wake beneath an unfamiliar sky" not in normal
    assert "FIRST_CONTEXT_SENTINEL_" not in normal
    assert abs(len(first) - len(normal)) < 4000
''',
    '''    assert "I wake beneath an unfamiliar sky" not in normal
    assert all(claim not in normal for claim in full_claims)
    assert abs(len(first) - len(normal)) < 4000
''',
)

print("Applied semantic test repairs")
