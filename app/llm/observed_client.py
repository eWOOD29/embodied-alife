from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.client import BrainResult, LocalLLMClient
from app.llm.prompts import consolidation_messages, decision_messages
from app.llm.schemas import ActionDecision, ConsolidationResult

T = TypeVar("T", bound=BaseModel)
DIRECTIONS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


@dataclass(slots=True)
class ObservedBrainResult(BrainResult[T], Generic[T]):
    finish_reason: str | None = None
    provider_response_id: str | None = None
    request_attempts: int | None = None
    policy_correction: str | None = None


class ObservedLocalLLMClient(LocalLLMClient):
    """Local client with provider metadata suitable for diagnostics and soak tests."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, http_client=http_client)
        self.last_model_catalog: dict[str, Any] | None = None
        self.status.update(
            generation_healthy=None,
            finish_reason=None,
            provider_response_id=None,
            request_attempts=None,
            policy_correction=None,
        )

    def public_configuration(self) -> dict[str, Any]:
        configuration = super().public_configuration()
        configuration["last_model_catalog"] = self.last_model_catalog
        return configuration

    async def discover_model_catalog(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        catalog = await super().discover_model_catalog(base_url=base_url, api_key=api_key)
        self.last_model_catalog = catalog
        return catalog

    @staticmethod
    def _exploration_direction(context: dict[str, Any]) -> str:
        facing = str((context.get("perception", {}).get("body") or {}).get("facing") or "north")
        try:
            index = DIRECTIONS.index(facing)
        except ValueError:
            index = 0
        # Turn roughly 90 degrees so a stationary loop does not repeatedly choose
        # the same heading. The controller still validates the resulting route.
        return DIRECTIONS[(index + 2) % len(DIRECTIONS)]

    def _apply_preexecution_policy(
        self,
        decision: ActionDecision,
        context: dict[str, Any],
    ) -> tuple[ActionDecision, str | None]:
        affordances = context.get("action_affordances") or {}
        need_semantics = affordances.get("need_semantics") or {}
        food_policy = affordances.get("food_policy") or {}
        recent = context.get("recent_outcomes") or []
        direction = self._exploration_direction(context)

        correction: str | None = None
        if decision.action == "eat" and not bool(need_semantics.get("eating_recommended")):
            correction = "eat_blocked_while_satiated"
        elif decision.action == "pick_up" and decision.target_id:
            target = (affordances.get("target_constraints") or {}).get(decision.target_id) or {}
            if target.get("appears_edible") and not bool(food_policy.get("collect_more_food")):
                correction = "food_collection_reserve_already_sufficient"
        elif decision.action == "look":
            previous = recent[-1] if recent else None
            if previous and previous.get("success") and previous.get("action") == "look":
                correction = "consecutive_stationary_look"

        if correction is None:
            return decision, None

        replacement = decision.model_copy(
            update={
                "intent": "Move to gain new spatial information instead of repeating an unproductive or unnecessary action.",
                "action": "move",
                "target_id": None,
                "direction": direction,
                "duration_seconds": max(2.0, min(5.0, decision.duration_seconds)),
                "reason": f"Pre-execution policy correction: {correction}.",
                "plan": [],
                "belief_updates": {},
                "memory_write": None,
            }
        )
        return replacement, correction

    async def decide(self, context: dict[str, Any]) -> BrainResult[ActionDecision]:
        if self.settings.no_llm or not self.settings.llm_model:
            decision = self.fallback.decide(context["perception"])
            return ObservedBrainResult(decision, "fallback", "LLM disabled or unconfigured")
        try:
            result = await self._request(decision_messages(context), ActionDecision)
            corrected, correction = self._apply_preexecution_policy(result.value, context)
            if correction:
                result.value = corrected
                result.status = "ok-policy-corrected"
                result.policy_correction = correction
                self.status.update(policy_correction=correction)
            else:
                self.status.update(policy_correction=None)
            return result
        except Exception as exc:  # noqa: BLE001
            decision = self.fallback.decide(context["perception"])
            error = f"{type(exc).__name__}: {exc}"
            reachable = bool(self.status.get("available"))
            self.status.update(
                mode="fallback",
                available=reachable,
                generation_healthy=False,
                last_error=error,
            )
            return ObservedBrainResult(decision, "fallback", "LLM request failed", error=error)

    async def consolidate(self, context: dict[str, Any]) -> BrainResult[ConsolidationResult]:
        if self.settings.no_llm or not self.settings.llm_model:
            value = self.fallback.consolidate(context)
            return ObservedBrainResult(value, "fallback", "LLM disabled or unconfigured")
        try:
            return await self._request(consolidation_messages(context), ConsolidationResult)
        except Exception as exc:  # noqa: BLE001
            value = self.fallback.consolidate(context)
            error = f"{type(exc).__name__}: {exc}"
            reachable = bool(self.status.get("available"))
            self.status.update(
                mode="fallback",
                available=reachable,
                generation_healthy=False,
                last_error=error,
            )
            return ObservedBrainResult(value, "fallback", "LLM reflection failed", error=error)

    async def _request(self, messages: list[dict[str, str]], model_type: type[T]) -> ObservedBrainResult[T]:
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
        for attempt in range(1, 3):
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
                choice = (data.get("choices") or [{}])[0]
                finish_reason = choice.get("finish_reason")
                provider_response_id = data.get("id")
                self.status.update(
                    mode="llm",
                    available=True,
                    generation_healthy=True,
                    model=self.settings.llm_model,
                    base_url=self.settings.llm_base_url,
                    last_error=None,
                    last_latency_ms=round(latency_ms, 1),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    finish_reason=finish_reason,
                    provider_response_id=provider_response_id,
                    request_attempts=attempt,
                )
                return ObservedBrainResult(
                    parsed,
                    "llm",
                    "ok",
                    latency_ms=latency_ms,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    raw_content=content,
                    finish_reason=finish_reason,
                    provider_response_id=provider_response_id,
                    request_attempts=attempt,
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
