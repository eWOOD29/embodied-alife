from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.serialization import json_safe_dict


@dataclass(slots=True)
class Event:
    sim_time: float
    kind: str
    message: str
    data: dict[str, Any]
    importance: float = 0.3

    def to_dict(self) -> dict[str, Any]:
        return json_safe_dict(self, max_depth=8, max_items=256, max_text=4000)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(**data)
