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
    if type(value) is bool:
        return default
    if type(value) in {int, float}:
        candidate: int | float | str = value
    elif type(value) is str:
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
    if type(value) is str:
        return _bounded_text(value, maximum)
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(max(-int(MAX_FINITE_MAGNITUDE), min(int(MAX_FINITE_MAGNITUDE), value)))
    if type(value) is float:
        number = finite_number(value)
        return None if number is None else str(number)
    if isinstance(value, Enum):
        try:
            return _safe_key(value.value, maximum)
        except Exception:
            return None
    return None


def _truncation_key(result: Mapping[str, Any]) -> str:
    key = "__truncated__"
    suffix = 2
    while key in result:
        key = f"__truncated__#{suffix}"
        suffix += 1
    return key


def _builtin_dict_items(value: Any, limit: int) -> tuple[list[tuple[Any, Any]], bool]:
    if not issubclass(type(value), dict):
        return [], False
    result: list[tuple[Any, Any]] = []
    truncated = False
    try:
        iterator = iter(dict.items(value))
        for _ in range(max(0, limit) + 1):
            try:
                result.append(next(iterator))
            except StopIteration:
                break
        if len(result) > limit:
            truncated = True
            result = result[:limit]
    except Exception:
        return [], True
    return result, truncated


def _builtin_sequence_items(value: Any, limit: int) -> tuple[list[Any], bool]:
    result: list[Any] = []
    try:
        if issubclass(type(value), list):
            length = list.__len__(value)
            take = min(length, limit + 1)
            result = [list.__getitem__(value, index) for index in range(take)]
        elif issubclass(type(value), tuple):
            length = tuple.__len__(value)
            take = min(length, limit + 1)
            result = [tuple.__getitem__(value, index) for index in range(take)]
        elif issubclass(type(value), deque):
            iterator = deque.__iter__(value)
            for _ in range(limit + 1):
                try:
                    result.append(next(iterator))
                except StopIteration:
                    break
        else:
            return [], False
    except Exception:
        return [], True
    truncated = len(result) > limit
    return result[:limit], truncated


def _builtin_set_items(value: Any, limit: int) -> tuple[list[Any], bool]:
    try:
        if issubclass(type(value), set):
            size = set.__len__(value)
            iterator = set.__iter__(value)
        elif issubclass(type(value), frozenset):
            size = frozenset.__len__(value)
            iterator = frozenset.__iter__(value)
        else:
            return [], False
        if size > limit:
            return [], True
        result = []
        for _ in range(size):
            result.append(next(iterator))
        return result, False
    except Exception:
        return [], True


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
        if current is None or type(current) is bool:
            return current
        if type(current) is int:
            return max(-int(MAX_FINITE_MAGNITUDE), min(int(MAX_FINITE_MAGNITUDE), current))
        if type(current) is float:
            return finite_number(current)
        if type(current) is str:
            return _bounded_text(current, max_text)
        if type(current) in {bytes, bytearray, memoryview}:
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

        if issubclass(type(current), dict):
            active.add(identity)
            try:
                result: dict[str, Any] = {}
                selected: list[tuple[str, Any]] = []
                raw_items, truncated = _builtin_dict_items(current, item_limit)
                for raw_key, raw_value in raw_items:
                    if not budget.take_source():
                        truncated = True
                        break
                    key = _safe_key(raw_key, 160)
                    if key is not None:
                        selected.append((key, raw_value))
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

        if issubclass(type(current), (list, tuple, deque)):
            active.add(identity)
            try:
                result: list[Any] = []
                raw_items, truncated = _builtin_sequence_items(current, item_limit)
                for item in raw_items:
                    if not budget.take_source():
                        truncated = True
                        break
                    result.append(project(item, depth + 1))
                if truncated:
                    if len(result) >= item_limit:
                        result[-1] = TRUNCATED
                    else:
                        result.append(TRUNCATED)
                return result
            finally:
                active.discard(identity)

        if issubclass(type(current), (set, frozenset)):
            active.add(identity)
            try:
                raw_items, omitted = _builtin_set_items(current, item_limit)
                if omitted:
                    return [UNORDERED_OMITTED]
                projected: list[Any] = []
                for item in raw_items:
                    if not budget.take_source():
                        return [UNORDERED_OMITTED]
                    projected.append(project(item, depth + 1))
                projected.sort(
                    key=lambda item: json.dumps(
                        item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                )
                return projected
            finally:
                active.discard(identity)

        return "<unsupported>"

    return project(value, 0)


def json_safe_dict(value: Any, **kwargs: Any) -> dict[str, Any]:
    projected = json_safe(value, **kwargs)
    return projected if type(projected) is dict else {}


def strict_json_dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(json_safe(value, **kwargs), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
