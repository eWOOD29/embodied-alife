from __future__ import annotations

import math
from collections import deque
from typing import Any, TypeVar

from app.serialization import finite_number

T = TypeVar("T")


def exact_dict(value: Any) -> dict[Any, Any]:
    """Accept only the built-in dict so hostile Mapping implementations are never enumerated."""
    return value if type(value) is dict else {}


def exact_sequence(value: Any, *, limit: int = 4096) -> list[Any]:
    """Copy a bounded prefix from exact built-in ordered containers only."""
    bounded = max(0, min(100_000, limit if type(limit) is int else 0))
    if type(value) is list:
        return value[:bounded]
    if type(value) is tuple:
        return list(value[:bounded])
    if type(value) is deque:
        result: list[Any] = []
        iterator = iter(value)
        for _ in range(bounded):
            try:
                result.append(next(iterator))
            except StopIteration:
                break
        return result
    return []


def exact_tail(value: Any, *, limit: int, scan_limit: int = 4096) -> list[Any]:
    """Return a bounded tail without accepting or invoking hostile subclasses."""
    keep = max(0, min(100_000, limit if type(limit) is int else 0))
    scan = max(0, min(100_000, scan_limit if type(scan_limit) is int else 0))
    if keep == 0:
        return []
    source = exact_sequence(value, limit=scan)
    return source[-keep:]


def exact_text(value: Any, *, maximum: int = 160, allow_empty: bool = False) -> str | None:
    """Normalize exact supported scalar types without arbitrary conversion hooks."""
    if type(value) is str:
        text = value
    elif type(value) is int:
        text = str(value)
    elif type(value) is float:
        number = finite_number(value)
        if number is None:
            return None
        text = str(number)
    elif type(value) is bool:
        text = "true" if value else "false"
    else:
        return None
    text = text.replace("\x00", "").strip()
    if len(text) > maximum or (not allow_empty and not text):
        return None
    return text


def builtin_dict_items(value: Any, *, limit: int = 4096) -> list[tuple[Any, Any]]:
    """Read built-in dict storage without invoking subclass overrides."""
    if not issubclass(type(value), dict):
        return []
    bounded = max(0, min(100_000, limit if type(limit) is int else 0))
    result: list[tuple[Any, Any]] = []
    try:
        iterator = iter(dict.items(value))
        for _ in range(bounded):
            try:
                result.append(next(iterator))
            except StopIteration:
                break
    except Exception:
        return []
    return result


def builtin_dict_copy(value: Any, *, limit: int = 4096) -> dict[Any, Any]:
    return {key: item for key, item in builtin_dict_items(value, limit=limit)}


def builtin_dict_get(value: Any, key: Any, default: Any = None) -> Any:
    if not issubclass(type(value), dict):
        return default
    try:
        return dict.get(value, key, default)
    except Exception:
        return default


def builtin_sequence(value: Any, *, limit: int = 4096) -> list[Any]:
    """Read built-in ordered-container storage without invoking subclass overrides."""
    bounded = max(0, min(100_000, limit if type(limit) is int else 0))
    result: list[Any] = []
    try:
        if issubclass(type(value), list):
            length = min(list.__len__(value), bounded)
            for index in range(length):
                result.append(list.__getitem__(value, index))
            return result
        if issubclass(type(value), tuple):
            length = min(tuple.__len__(value), bounded)
            for index in range(length):
                result.append(tuple.__getitem__(value, index))
            return result
        if issubclass(type(value), deque):
            iterator = deque.__iter__(value)
            for _ in range(bounded):
                try:
                    result.append(next(iterator))
                except StopIteration:
                    break
            return result
    except Exception:
        return []
    return []


def builtin_tail(value: Any, *, limit: int, scan_limit: int = 4096) -> list[Any]:
    keep = max(0, min(100_000, limit if type(limit) is int else 0))
    source = builtin_sequence(value, limit=scan_limit)
    return source[-keep:] if keep else []


def records(value: Any, record_type: type[T], *, limit: int = 10000) -> list[T]:
    result: list[T] = []
    source = exact_dict(value)
    try:
        iterator = iter(source.values())
        for _ in range(max(0, min(100_000, limit if type(limit) is int else 0))):
            try:
                item = next(iterator)
            except StopIteration:
                break
            if type(item) is record_type:
                result.append(item)
    except Exception:
        return []
    return result


def finite(
    value: Any,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    return finite_number(value, default, minimum=minimum, maximum=maximum)


def integer(
    value: Any,
    default: int | None = None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    number = finite(value)
    if number is None:
        return default
    parsed = int(number)
    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


def strict_text(value: Any, *, maximum: int = 160, allow_empty: bool = False) -> str | None:
    if type(value) is not str or len(value) > maximum or (not allow_empty and not value):
        return None
    return value


def exact_bool(value: Any, default: bool | None = None) -> bool | None:
    return value if type(value) is bool else default


def exact_weather(value: Any) -> str | None:
    """Return a controlled weather token or honest unknown state."""
    if type(value) is not str:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"clear", "rain", "storm", "fog", "snow"} else None


def finite_pair(x: Any, y: Any, *, maximum: float = 1_000_000.0) -> tuple[float, float] | None:
    safe_x = finite(x, None, minimum=-maximum, maximum=maximum)
    safe_y = finite(y, None, minimum=-maximum, maximum=maximum)
    if safe_x is None or safe_y is None:
        return None
    return safe_x, safe_y


def safe_hypot(x1: Any, y1: Any, x2: Any, y2: Any) -> float | None:
    left = finite_pair(x1, y1)
    right = finite_pair(x2, y2)
    if left is None or right is None:
        return None
    distance = math.hypot(left[0] - right[0], left[1] - right[1])
    return distance if math.isfinite(distance) else None
