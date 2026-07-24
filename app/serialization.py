from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_ITEMS = 256
DEFAULT_MAX_TEXT = 4000
DEFAULT_MAX_NODES = 8192
MAX_FINITE_MAGNITUDE = 1_000_000_000_000_000.0


class _Budget:
    __slots__ = ("remaining",)

    def __init__(self, maximum: int) -> None:
        self.remaining = max(1, int(maximum))

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def finite_number(
    value: Any,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    """Convert a scalar to a bounded finite float without treating booleans as numbers."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    lower = -MAX_FINITE_MAGNITUDE if minimum is None else minimum
    upper = MAX_FINITE_MAGNITUDE if maximum is None else maximum
    return max(lower, min(upper, number))


def _bounded_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    if maximum <= 1:
        return value[:maximum]
    return value[: maximum - 1] + "…"


def _safe_key(value: Any, maximum: int) -> str | None:
    if isinstance(value, str):
        return _bounded_text(value, maximum)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(max(-int(MAX_FINITE_MAGNITUDE), min(int(MAX_FINITE_MAGNITUDE), value)))
    if isinstance(value, float):
        number = finite_number(value)
        return None if number is None else str(number)
    if isinstance(value, Enum):
        return _safe_key(value.value, maximum)
    return None


def json_safe(
    value: Any,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_text: int = DEFAULT_MAX_TEXT,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> Any:
    """Return a deterministic, bounded value accepted by strict JSON encoders.

    Unknown objects never use repr() or class-qualified names. Circular references,
    excessive depth, oversized containers, binary values, and non-finite numbers
    degrade to explicit inert sentinels.
    """

    budget = _Budget(max_nodes)
    active: set[int] = set()

    def project(current: Any, depth: int) -> Any:
        if not budget.take():
            return "<max-nodes>"
        if depth > max_depth:
            return "<max-depth>"
        if current is None or isinstance(current, bool):
            return current
        if isinstance(current, int):
            return max(-int(MAX_FINITE_MAGNITUDE), min(int(MAX_FINITE_MAGNITUDE), current))
        if isinstance(current, float):
            return finite_number(current)
        if isinstance(current, str):
            return _bounded_text(current, max_text)
        if isinstance(current, (bytes, bytearray, memoryview)):
            return f"<binary:{min(len(current), int(MAX_FINITE_MAGNITUDE))}>"
        if isinstance(current, Path):
            return "<path-omitted>"
        if isinstance(current, (datetime, date)):
            return _bounded_text(current.isoformat(), max_text)
        if isinstance(current, Enum):
            return project(current.value, depth + 1)

        identity = id(current)
        if identity in active:
            return "<circular>"

        if is_dataclass(current) and not isinstance(current, type):
            active.add(identity)
            try:
                result: dict[str, Any] = {}
                for field_info in fields(current)[:max_items]:
                    result[field_info.name] = project(getattr(current, field_info.name), depth + 1)
                return result
            finally:
                active.discard(identity)

        if isinstance(current, Mapping):
            active.add(identity)
            try:
                keyed: list[tuple[str, Any]] = []
                for raw_key, raw_value in current.items():
                    key = _safe_key(raw_key, 160)
                    if key is not None:
                        keyed.append((key, raw_value))
                keyed.sort(key=lambda item: item[0])
                result: dict[str, Any] = {}
                for key, raw_value in keyed[:max_items]:
                    unique_key = key
                    suffix = 2
                    while unique_key in result:
                        unique_key = _bounded_text(f"{key}#{suffix}", 160)
                        suffix += 1
                    result[unique_key] = project(raw_value, depth + 1)
                return result
            finally:
                active.discard(identity)

        if isinstance(current, (list, tuple, deque)):
            active.add(identity)
            try:
                return [project(item, depth + 1) for item in list(current)[:max_items]]
            finally:
                active.discard(identity)

        if isinstance(current, (set, frozenset)):
            active.add(identity)
            try:
                projected = [project(item, depth + 1) for item in current]
                projected.sort(
                    key=lambda item: json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
                return projected[:max_items]
            finally:
                active.discard(identity)

        return "<unsupported>"

    return project(value, 0)


def json_safe_dict(value: Any, **kwargs: Any) -> dict[str, Any]:
    projected = json_safe(value, **kwargs)
    return projected if isinstance(projected, dict) else {}


def strict_json_dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(json_safe(value, **kwargs), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
