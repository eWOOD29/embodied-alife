from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.fallback import FallbackBrain
from app.llm.prompts import consolidation_messages, decision_messages
from app.llm.schemas import ActionDecision, ConsolidationResult

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class BrainResult(Generic[T]):
    value: T
    source: str
    status: str
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    raw_content: str | None = None


class LocalLLMClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._provided_client = http_client
        self.fallback = FallbackBrain()
        self.status: dict[str, Any] = {
            "mode": "fallback" if settings.no_llm or not settings.llm_model else "configured",
            "available": False,
            "model": settings.llm_model or None,
            "base_url": settings.llm_base_url,
            "last_error": None,
            "last_latency_ms": None,
            "prompt_tokens": None,
            "completion_tokens": None,
        }

    async def check_status(self) -> dict[str, Any]:
        if self.settings.no_llm or not self.settings.llm_model:
            self.status.update(mode="fallback", available=False, last_error="LLM disabled or LLM_MODEL is empty")
            return dict(self.status)
        try:
            async with self._client_context() as client:
                response = await client.get(f"{self.settings.llm_base_url}/models", headers=self._headers())
                response.raise_for_status()
            self.status.update(mode="llm", available=True, last_error=None)
        except Exception as exc:  # noqa: BLE001
            self.status.update(mode="fallback", available=False, last_error=f"{type(exc).__name__}: {exc}")
        return dict(self.status)

    async def decide(self, context: dict[str, Any]) -> BrainResult[ActionDecision]:
        if self.settings.no_llm or not self.settings.llm_model:
            decision = self.fallback.decide(context["perception"])
            return BrainResult(decision, "fallback", "LLM disabled or unconfigured")
        try:
            return await self._request(decision_messages(context), ActionDecision)
        except Exception as exc:  # noqa: BLE001
            decision = self.fallback.decide(context["perception"])
            error = f"{type(exc).__name__}: {exc}"
            self.status.update(mode="fallback", available=False, last_error=error)
            return BrainResult(decision, "fallback", "LLM request failed", error=error)

    async def consolidate(self, context: dict[str, Any]) -> BrainResult[ConsolidationResult]:
        if self.settings.no_llm or not self.settings.llm_model:
            value = self.fallback.consolidate(context)
            return BrainResult(value, "fallback", "LLM disabled or unconfigured")
        try:
            return await self._request(consolidation_messages(context), ConsolidationResult)
        except Exception as exc:  # noqa: BLE001
            value = self.fallback.consolidate(context)
            error = f"{type(exc).__name__}: {exc}"
            self.status.update(mode="fallback", available=False, last_error=error)
            return BrainResult(value, "fallback", "LLM reflection failed", error=error)

    async def _request(self, messages: list[dict[str, str]], model_type: type[T]) -> BrainResult[T]:
        started = time.perf_counter()
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with self._client_context() as client:
                    response = await client.post(
                        f"{self.settings.llm_base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                content = self._extract_content(data)
                parsed = model_type.model_validate_json(self._clean_json(content))
                latency_ms = (time.perf_counter() - started) * 1000
                usage = data.get("usage") or {}
                self.status.update(
                    mode="llm",
                    available=True,
                    last_error=None,
                    last_latency_ms=round(latency_ms, 1),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
                return BrainResult(
                    parsed,
                    "llm",
                    "ok",
                    latency_ms=latency_ms,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    raw_content=content,
                )
            except (httpx.HTTPError, ValueError, KeyError, IndexError, ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                payload["messages"] = messages + [
                    {
                        "role": "user",
                        "content": "Your previous response was invalid. Return one JSON object only, exactly matching the schema.",
                    }
                ]
        assert last_error is not None
        raise last_error

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Model response did not contain text content")
        return content

    @staticmethod
    def _clean_json(content: str) -> str:
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model response")
        return cleaned[start : end + 1]

    def _client_context(self):
        if self._provided_client is not None:
            return _BorrowedClient(self._provided_client)
        return httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds)


class _BorrowedClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
