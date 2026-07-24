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
TRUNCATED = "<truncated>"
UNORDERED_OMITTED = "<unordered-omitted>"


class _Budget:
    __slots__ = ("nodes", "source")

    def __init__(self, maximum_nodes: int, maximum_source: int) -> None:
        self.nodes = max(1, int(maximum_nodes))
        self.source = max(1, int(maximum_source))

    def take_node(self) -> bool:
        if self.nodes <= 0:
            return False
        self.nodes -= 1
        return True

    def take_source(self) -> bool:
        if self.source <= 0:
            return False
        self.source -= 1
        return True


def finite_number(
    value: Any,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    """Convert an explicitly supported scalar to a bounded finite float.

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


def _truncation_key(result: Mapping[str, Any]) -> str:
    key = "__truncated__"
    suffix = 2
    while key in result:
        key = f"__truncated__#{suffix}"
        suffix += 1
    return key


def json_safe(
    value: Any,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_text: int = DEFAULT_MAX_TEXT,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_source_items: int | None = None,
) -> Any:
    """Return deterministic bounded strict-JSON data with bounded source work.

    Mapping selection follows insertion order, which is deterministic for normal Python
    mappings and avoids enumerating/sorting the full source. Ordered sequences are scanned
    only through the output boundary plus one truncation probe. Oversized unordered sets are
    omitted rather than fully projected or sorted. Unknown objects never use repr() or str().
    """

    item_limit = max(1, int(max_items))
    source_limit = max_source_items if max_source_items is not None else max(max_nodes * 2, item_limit + 1)
    budget = _Budget(max_nodes, source_limit)
    active: set[int] = set()

    def project(current: Any, depth: int) -> Any:
        if not budget.take_node():
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
                dataclass_fields = fields(current)
                truncated = len(dataclass_fields) > item_limit
                selected = dataclass_fields[: item_limit - 1] if truncated and item_limit > 1 else dataclass_fields[:item_limit]
                for field_info in selected:
                    if not budget.take_source():
                        result[_truncation_key(result)] = True
                        break
                    try:
                        raw_value = getattr(current, field_info.name)
                    except Exception:
                        raw_value = "<unavailable>"
                    result[field_info.name] = project(raw_value, depth + 1)
                if truncated:
                    result[_truncation_key(result)] = True
                return result
            finally:
                active.discard(identity)

        if isinstance(current, Mapping):
            active.add(identity)
            try:
                result: dict[str, Any] = {}
                selected: list[tuple[str, Any]] = []
                truncated = False
                try:
                    iterator = iter(current.items())
                except Exception:
                    return {"__omitted__": "<unavailable-mapping>"}
                while len(selected) < item_limit + 1:
                    if not budget.take_source():
                        truncated = True
                        break
                    try:
                        raw_key, raw_value = next(iterator)
                    except StopIteration:
                        break
                    except Exception:
                        truncated = True
                        break
                    key = _safe_key(raw_key, 160)
                    if key is not None:
                        selected.append((key, raw_value))
                if len(selected) > item_limit:
                    truncated = True
                    selected = selected[:item_limit]
                if truncated and item_limit > 1 and len(selected) >= item_limit:
                    selected = selected[: item_limit - 1]
                for key, raw_value in selected:
                    unique_key = key
                    suffix = 2
                    while unique_key in result:
                        unique_key = _bounded_text(f"{key}#{suffix}", 160)
                        suffix += 1
                    result[unique_key] = project(raw_value, depth + 1)
                if truncated:
                    result[_truncation_key(result)] = True
                return result
            finally:
                active.discard(identity)

        if isinstance(current, (list, tuple, deque)):
            active.add(identity)
            try:
                result: list[Any] = []
                truncated = False
                try:
                    iterator = iter(current)
                except Exception:
                    return ["<unavailable-sequence>"]
                while len(result) < item_limit + 1:
                    if not budget.take_source():
                        truncated = True
                        break
                    try:
                        item = next(iterator)
                    except StopIteration:
                        break
                    except Exception:
                        truncated = True
                        break
                    result.append(project(item, depth + 1))
                if len(result) > item_limit:
                    truncated = True
                    result = result[:item_limit]
                if truncated:
                    if len(result) >= item_limit:
                        result[-1] = TRUNCATED
                    else:
                        result.append(TRUNCATED)
                return result
            finally:
                active.discard(identity)

        if isinstance(current, (set, frozenset)):
            active.add(identity)
            try:
                try:
                    size = len(current)
                except Exception:
                    return [UNORDERED_OMITTED]
                if size > item_limit:
                    return [UNORDERED_OMITTED]
                projected: list[Any] = []
                try:
                    iterator = iter(current)
                except Exception:
                    return [UNORDERED_OMITTED]
                for _ in range(size):
                    if not budget.take_source():
                        return [UNORDERED_OMITTED]
                    try:
                        item = next(iterator)
                    except (StopIteration, Exception):
                        return [UNORDERED_OMITTED]
                    projected.append(project(item, depth + 1))
                projected.sort(
                    key=lambda item: json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
                return projected
            finally:
                active.discard(identity)

        return "<unsupported>"

    return project(value, 0)


def json_safe_dict(value: Any, **kwargs: Any) -> dict[str, Any]:
    projected = json_safe(value, **kwargs)
    return projected if isinstance(projected, dict) else {}


def strict_json_dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(json_safe(value, **kwargs), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
