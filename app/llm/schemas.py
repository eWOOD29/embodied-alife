from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ActionName = Literal[
    "move",
    "move_to",
    "look",
    "inspect",
    "pick_up",
    "drop",
    "eat",
    "drink",
    "sleep",
    "rest",
    "build",
    "speak",
    "flee",
    "wait",
]


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["remember"] = "remember"
    category: Literal[
        "survival",
        "locations",
        "affordances",
        "environment",
        "entities",
        "projects",
        "beliefs",
        "reflections",
        "daily",
    ]
    title: str = Field(min_length=3, max_length=120)
    content: str = Field(min_length=5, max_length=4000)
    importance: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in tags:
            normalized = "-".join(tag.strip().lower().split())
            if normalized and normalized not in cleaned:
                cleaned.append(normalized[:40])
        return cleaned


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=240)
    action: ActionName
    target_id: str | None = Field(default=None, max_length=120)
    direction: Literal["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"] | None = None
    duration_seconds: float = Field(default=2.0, ge=0.2, le=120.0)
    interrupt_if: list[
        Literal[
            "danger_detected",
            "damage_taken",
            "energy_critical",
            "hydration_critical",
            "target_unreachable",
            "weather_worsens",
        ]
    ] = Field(default_factory=list, max_length=6)
    reason: str = Field(min_length=1, max_length=500)
    plan: list[str] = Field(default_factory=list, max_length=6)
    belief_updates: dict[str, str] = Field(default_factory=dict)
    memory_write: MemoryWrite | None = None


class ConsolidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=10, max_length=2500)
    memories: list[MemoryWrite] = Field(default_factory=list, max_length=5)
    belief_updates: dict[str, str] = Field(default_factory=dict)
    next_intention: str | None = Field(default=None, max_length=240)
