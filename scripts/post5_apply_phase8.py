from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


patch(
    "app/simulation/actions.py",
    '''def _finite_number(value: Any, default: float | None = None) -> float | None:
    return finite_number(value, default)
''',
    '''def _finite_number(
    value: Any,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    return finite_number(value, default, minimum=minimum, maximum=maximum)
''',
)
patch("app/diagnostics.py", '"schema_version": 4,', '"schema_version": 3,')
print("post5 phase8 applied")
