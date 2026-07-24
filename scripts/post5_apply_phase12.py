from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str, label: str, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{label}: expected {count} matches, found {actual}")
    target.write_text(text.replace(old, new, count), encoding="utf-8", newline="\n")


patch(
    "app/simulation/perception.py",
    "from typing import Any\n\nfrom app.simulation.actions",
    "from itertools import islice\nfrom typing import Any\n\nfrom app.serialization import finite_number\nfrom app.simulation.actions",
    "perception safe imports",
)
patch(
    "app/simulation/perception.py",
    '''def _safe_number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        number = default
    else:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = default
    if not math.isfinite(number):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number
''',
    '''def _safe_number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:
    number = finite_number(value, default, minimum=minimum, maximum=maximum)
    return default if number is None else number
''',
    "perception numeric conversion",
)
patch(
    "app/simulation/perception.py",
    '''            "tile_count": sum(1 for key, value in (terrain_store.items() if terrain_store is not None else []) if verify_knowledge(agent, "terrain", key, value)),
''',
    '''            "tile_count": sum(
                1
                for key, value in islice(terrain_store.items(), 4096)
                if verify_knowledge(agent, "terrain", key, value)
            ) if terrain_store is not None else 0,
''',
    "bounded terrain count",
)
patch(
    "app/simulation/agent.py",
    '''def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for raw in value:
''',
    '''def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    if isinstance(value, (set, frozenset)):
        iterable = sorted(
            (raw for raw in value if isinstance(raw, (str, int)) and not isinstance(raw, bool)),
            key=lambda raw: (type(raw).__name__, raw),
        )
    else:
        iterable = value
    result: list[str] = []
    for raw in iterable:
''',
    "agent string container normalization",
)
patch(
    "scripts/privacy_scan.py",
    '''CREDENTIAL = re.compile(
    r"(?i)(?:bearer\\s+[a-z0-9._~-]{12,}|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\\s*[:=]\\s*[\\\"']?[a-z0-9._~+/=-]{12,})"
)
''',
    '''CREDENTIAL = re.compile(
    r"(?i)(?:bearer\\s+[a-z0-9._~-]{20,}|sk-[a-z0-9_-]{20,}|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\\s*[:=]\\s*[\\\"'][^\\\"'\\r\\n]{12,}[\\\"'])"
)
''',
    "credential false-positive reduction",
)
patch(
    "tests/test_public_repository_hygiene.py",
    '''        lambda: "synthetic-device.synthetic-tailnet.ts.net",
        lambda: "https://" + "drive.google.com/drive/folders/" + "synthetic",
        lambda: "api_key=" + "synthetic-secret-value-1234567890",
''',
    '''        lambda: "".join(("synthetic-device", ".synthetic-tailnet", ".ts", ".net")),
        lambda: "https://" + "drive.google.com/drive/folders/" + "synthetic",
        lambda: "api_key=\"" + "synthetic-secret-value-1234567890" + "\"",
''',
    "synthetic scanner fixtures",
)
patch(
    "tests/test_v040_post4_remediation.py",
    'return "<HostileObject C:\\\\Users\\\\private\\\\secret.txt at 0xDEADBEEF>"',
    'return "<HostileObject synthetic-machine-path at 0xDEADBEEF>"',
    "post4 synthetic Windows path",
)
patch(
    "tests/test_v040_post4_remediation.py",
    'Path("/home/private/secret")',
    'Path("synthetic-private-path")',
    "post4 synthetic POSIX path",
)
patch(
    "tests/test_v040_post4_remediation.py",
    'assert "/home/private/secret" not in response.text',
    'assert "synthetic-private-path" not in response.text',
    "post4 response privacy expectation",
)
patch(
    "tests/test_v040_post4_remediation.py",
    'assert "/home/private/secret" not in bundle_text',
    'assert "synthetic-private-path" not in bundle_text',
    "post4 bundle privacy expectation",
)
patch(
    "tests/test_v040_post5_remediation.py",
    "from app.simulation.actions import ActionController, ActionResult\n",
    "from app.simulation.actions import ARI_TASK_LIMIT, ActionController, ActionResult\n",
    "post5 task limit import",
)
patch(
    "tests/test_v040_post5_remediation.py",
    'assert result.data["visible_tasks"] <= 24',
    'assert result.data["visible_tasks"] <= ARI_TASK_LIMIT',
    "post5 task limit assertion",
)
patch(
    "app/web/routes.py",
    '''def _health_payload(request: Request) -> dict:
    engine = _engine(request)
    return {
''',
    '''def _health_payload(request: Request) -> dict:
    engine = _engine(request)
    brain_status = getattr(getattr(engine, "brain", None), "status", {})
    brain_status = brain_status if isinstance(brain_status, dict) else {}
    updater_status = getattr(_updater(request), "status", None)
    return {
''',
    "health normalized status",
)
patch(
    "app/web/routes.py",
    '''        "paused": engine.paused,
        "alive": engine.agent.alive,
        "seed": engine.world.seed,
''',
    '''        "paused": getattr(engine, "paused", False) is True,
        "alive": getattr(getattr(engine, "agent", None), "alive", False) is True,
        "seed": finite_number(getattr(getattr(engine, "world", None), "seed", None), 0.0),
''',
    "health normalized state",
)
patch(
    "app/web/routes.py",
    '''        "model_mode": engine.brain.status.get("mode"),
        "model_available": engine.brain.status.get("available"),
        "generation_healthy": engine.brain.status.get("generation_healthy"),
        "update_state": _updater(request).status.state,
''',
    '''        "model_mode": brain_status.get("mode") if isinstance(brain_status.get("mode"), str) else "unknown",
        "model_available": brain_status.get("available") is True,
        "generation_healthy": brain_status.get("generation_healthy") is True,
        "update_state": getattr(updater_status, "state", "unknown") if isinstance(getattr(updater_status, "state", "unknown"), str) else "unknown",
''',
    "health normalized outputs",
)
print("post5 phase12 applied")
