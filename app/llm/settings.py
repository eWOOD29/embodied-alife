from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings


class LLMSettingsStore:
    """Persist runtime LLM choices outside the managed application tree."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_settings(cls, settings: Settings) -> "LLMSettingsStore":
        return cls(settings.runtime_dir / "llm-settings.json")

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def apply(self, settings: Settings) -> None:
        payload = self.load()
        if not payload:
            return
        if isinstance(payload.get("enabled"), bool):
            settings.no_llm = not payload["enabled"]
        if isinstance(payload.get("base_url"), str) and payload["base_url"].strip():
            settings.llm_base_url = payload["base_url"].strip().rstrip("/")
        if isinstance(payload.get("api_key"), str):
            settings.llm_api_key = payload["api_key"]
        if isinstance(payload.get("model"), str):
            settings.llm_model = payload["model"].strip()
        if isinstance(payload.get("context_length"), int):
            settings.llm_context_length = payload["context_length"]
        if isinstance(payload.get("timeout_seconds"), (int, float)):
            settings.llm_timeout_seconds = float(payload["timeout_seconds"])
        if isinstance(payload.get("temperature"), (int, float)):
            settings.llm_temperature = float(payload["temperature"])
        if isinstance(payload.get("max_tokens"), int):
            settings.llm_max_tokens = payload["max_tokens"]

    def save(self, settings: Settings) -> None:
        payload = {
            "schema_version": 1,
            "enabled": not settings.no_llm,
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key,
            "model": settings.llm_model,
            "context_length": settings.llm_context_length,
            "timeout_seconds": settings.llm_timeout_seconds,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
