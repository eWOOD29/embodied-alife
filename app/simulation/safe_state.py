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
    if type(value) is list:
        return value[:limit]
    if type(value) is tuple:
        return list(value[:limit])
    if type(value) is deque:
        result: list[Any] = []
        try:
            iterator = iter(value)
            for _ in range(limit):
                try:
                    result.append(next(iterator))
                except StopIteration:
                    break
        except Exception:
            return []
        return result
    return []


def records(value: Any, record_type: type[T], *, limit: int = 10000) -> list[T]:
    result: list[T] = []
    source = exact_dict(value)
    try:
        iterator = iter(source.values())
        for _ in range(limit):
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
