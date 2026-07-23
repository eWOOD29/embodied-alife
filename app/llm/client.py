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

    async def discover_model_catalog(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """Return LM Studio model metadata with loaded state when available."""
        resolved_url = self._validate_base_url(base_url or self.settings.llm_base_url)
        resolved_key = self.settings.llm_api_key if api_key is None else api_key
        headers = self._headers_for_key(resolved_key)
        server_root = self._server_root(resolved_url)

        async with self._client_context() as client:
            native_response = await client.get(f"{server_root}/api/v0/models", headers=headers)
            if native_response.status_code != 404:
                self._raise_for_lm_studio_error(native_response)
                payload = native_response.json()
                records = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(records, list):
                    raise ValueError("LM Studio returned an invalid /api/v0/models response")
                models = [self._normalize_native_model(item) for item in records if isinstance(item, dict)]
                models = [item for item in models if item["id"] and item["type"] in {"llm", "vlm", "unknown"}]
                models.sort(key=lambda item: (item["state"] != "loaded", item["display_name"].lower()))
                return {"models": models, "source": "lm-studio-native", "loaded_state_available": True}

            compatible_response = await client.get(f"{resolved_url}/models", headers=headers)
            self._raise_for_lm_studio_error(compatible_response)
            payload = compatible_response.json()
            records = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(records, list):
                raise ValueError("The model server returned an invalid /v1/models response")
            models = [
                {
                    "id": str(item.get("id", "")).strip(),
                    "display_name": str(item.get("id", "")).strip(),
                    "state": "unknown",
                    "type": "unknown",
                    "publisher": None,
                    "quantization": None,
                    "max_context_length": None,
                }
                for item in records
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
            models.sort(key=lambda item: item["display_name"].lower())
            return {"models": models, "source": "openai-compatible", "loaded_state_available": False}

    async def discover_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        catalog = await self.discover_model_catalog(base_url=base_url, api_key=api_key)
        loaded = [item["id"] for item in catalog["models"] if item["state"] == "loaded"]
        if catalog["loaded_state_available"]:
            return loaded
        return [item["id"] for item in catalog["models"]]

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
            catalog = await self.discover_model_catalog()
            models = catalog["models"]
            loaded = [item["id"] for item in models if item["state"] == "loaded"]
            selectable = loaded if catalog["loaded_state_available"] else [item["id"] for item in models]

            if len(loaded) == 1 and self.settings.llm_model not in loaded:
                self.settings.llm_model = loaded[0]
                self.store.save(self.settings)

            if not self.settings.llm_model:
                self.status.update(
                    mode="configured",
                    available=bool(selectable),
                    model=None,
                    last_error="Choose a loaded model" if selectable else "No LLM is loaded",
                )
                return dict(self.status)
            if self.settings.llm_model not in selectable:
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": model_type.__name__,
                    "strict": True,
                    "schema": model_type.model_json_schema(),
                },
            },
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
                    self._raise_for_lm_studio_error(response)
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
        return self._headers_for_key(self.settings.llm_api_key)

    @staticmethod
    def _headers_for_key(api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "***":
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _validate_base_url(value: str) -> str:
        resolved = value.strip().rstrip("/")
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL must be a valid HTTP or HTTPS URL")
        return resolved

    @staticmethod
    def _server_root(base_url: str) -> str:
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _normalize_native_model(item: dict[str, Any]) -> dict[str, Any]:
        model_id = str(item.get("id", "")).strip()
        display_name = str(item.get("display_name") or model_id).strip()
        state = str(item.get("state") or "unknown").strip().lower()
        model_type = str(item.get("type") or "unknown").strip().lower()
        quantization = item.get("quantization")
        if isinstance(quantization, dict):
            quantization = quantization.get("name")
        return {
            "id": model_id,
            "display_name": display_name or model_id,
            "state": state,
            "type": model_type,
            "publisher": item.get("publisher"),
            "quantization": quantization,
            "max_context_length": item.get("max_context_length"),
        }

    @staticmethod
    def _raise_for_lm_studio_error(response: httpx.Response) -> None:
        if not response.is_error:
            return
        detail = response.text.strip()
        if len(detail) > 1200:
            detail = detail[:1200] + "…"
        message = f"LM Studio returned HTTP {response.status_code}"
        if detail:
            message += f": {detail}"
        raise ValueError(message)

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
