from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.fallback import FallbackBrain
from app.llm.prompts import consolidation_messages, decision_messages
from app.llm.schemas import ActionDecision, ConsolidationResult
from app.llm.settings import LLMSettingsStore

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
        self.store = LLMSettingsStore.for_settings(settings)
        self.store.apply(settings)
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

    def public_configuration(self) -> dict[str, Any]:
        return {
            "enabled": not self.settings.no_llm,
            "base_url": self.settings.llm_base_url,
            "model": self.settings.llm_model,
            "context_length": self.settings.llm_context_length,
            "timeout_seconds": self.settings.llm_timeout_seconds,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "api_key_configured": bool(self.settings.llm_api_key and self.settings.llm_api_key != "***"),
            "status": dict(self.status),
        }

    async def discover_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        resolved_url = self._validate_base_url(base_url or self.settings.llm_base_url)
        resolved_key = self.settings.llm_api_key if api_key is None else api_key
        headers = {
            "Authorization": f"Bearer {resolved_key}",
            "Content-Type": "application/json",
        }
        async with self._client_context() as client:
            response = await client.get(f"{resolved_url}/models", headers=headers)
            response.raise_for_status()
            payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise ValueError("The model server returned an invalid /models response")
        return sorted(
            {
                str(item.get("id", "")).strip()
                for item in models
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            }
        )

    async def configure(
        self,
        *,
        enabled: bool,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
        context_length: int,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        resolved_url = self._validate_base_url(base_url)
        resolved_model = model.strip()
        if len(resolved_model) > 300:
            raise ValueError("Model ID is too long")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("Temperature must be between 0 and 2")
        if not 32 <= max_tokens <= 32768:
            raise ValueError("Maximum output tokens must be between 32 and 32768")
        if not 5 <= timeout_seconds <= 600:
            raise ValueError("Timeout must be between 5 and 600 seconds")
        if not 1024 <= context_length <= 262144:
            raise ValueError("Context length must be between 1024 and 262144")

        self.settings.no_llm = not enabled
        self.settings.llm_base_url = resolved_url
        self.settings.llm_model = resolved_model
        self.settings.llm_temperature = float(temperature)
        self.settings.llm_max_tokens = int(max_tokens)
        self.settings.llm_timeout_seconds = float(timeout_seconds)
        self.settings.llm_context_length = int(context_length)
        if api_key is not None and api_key.strip():
            self.settings.llm_api_key = api_key.strip()

        self.status.update(
            mode="configured" if enabled else "fallback",
            available=False,
            model=resolved_model or None,
            base_url=resolved_url,
            last_error=None,
            last_latency_ms=None,
            prompt_tokens=None,
            completion_tokens=None,
        )
        self.store.save(self.settings)
        await self.check_status()
        return self.public_configuration()

    async def check_status(self) -> dict[str, Any]:
        self.status.update(model=self.settings.llm_model or None, base_url=self.settings.llm_base_url)
        if self.settings.no_llm:
            self.status.update(mode="fallback", available=False, last_error="Local LLM is disabled")
            return dict(self.status)
        try:
            models = await self.discover_models()
            if not self.settings.llm_model and len(models) == 1:
                self.settings.llm_model = models[0]
                self.store.save(self.settings)
            if not self.settings.llm_model:
                self.status.update(
                    mode="configured",
                    available=bool(models),
                    model=None,
                    last_error="Choose a loaded model" if models else "No models are loaded",
                )
                return dict(self.status)
            if self.settings.llm_model not in models:
                self.status.update(
                    mode="fallback",
                    available=False,
                    model=self.settings.llm_model,
                    last_error=f"Model is not loaded: {self.settings.llm_model}",
                )
                return dict(self.status)
            self.status.update(mode="llm", available=True, model=self.settings.llm_model, last_error=None)
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
        for _attempt in range(2):
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
                    model=self.settings.llm_model,
                    base_url=self.settings.llm_base_url,
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
    def _validate_base_url(value: str) -> str:
        resolved = value.strip().rstrip("/")
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL must be a valid HTTP or HTTPS URL")
        return resolved

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
