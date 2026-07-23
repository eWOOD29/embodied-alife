from __future__ import annotations

import weakref
from pathlib import Path
from typing import Any

from app.config import Settings
from app.llm.observed_client import ObservedLocalLLMClient
from app.llm.schemas import ActionDecision, MemoryWrite
from app.memory.retrieval import retrieve_memories
from app.memory.vault import MemoryValidationError, MemoryVault
from app.simulation.actions import ActionResult
from app.simulation.affordances import build_action_affordances
from app.simulation.perception import build_perception
from app.simulation.scheduler import SimulationEngine as BaseSimulationEngine
from app.storage.database import Database


class SimulationEngine(BaseSimulationEngine):
    """Production engine with cognition guidance, observability, and authoritative memory commits."""

    _instances: weakref.WeakSet = weakref.WeakSet()

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        brain=None,
        vault: MemoryVault | None = None,
        load_existing: bool = True,
    ) -> None:
        resolved_brain = brain or ObservedLocalLLMClient(settings)
        super().__init__(
            settings,
            database=database,
            brain=resolved_brain,
            vault=vault,
            load_existing=load_existing,
        )
        self._instances.add(self)

    @classmethod
    def live_instance_count(cls, database_path: Path | str | None = None) -> int:
        instances = list(cls._instances)
        if database_path is None:
            return len(instances)
        resolved = Path(database_path).resolve()
        return sum(
            1
            for instance in instances
            if Path(instance.database.path).resolve() == resolved
        )

    def _recent_action_outcomes(self, limit: int = 8) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        current_decision: dict[str, Any] | None = None
        for event in self.events:
            if event.get("kind") == "decision":
                current_decision = (event.get("data") or {}).get("decision") or {}
                continue
            if event.get("kind") != "action_result":
                continue
            result = event.get("data") or {}
            if result.get("reason") == "started":
                continue
            outcomes.append(
                {
                    "sim_time": event.get("sim_time"),
                    "action": result.get("action") or (current_decision or {}).get("action"),
                    "target_id": (current_decision or {}).get("target_id"),
                    "success": bool(result.get("success")),
                    "reason": result.get("reason"),
                    "details": result.get("details") or event.get("message"),
                }
            )
        return outcomes[-limit:]

    def _correct_decision(
        self,
        decision: ActionDecision,
        action_affordances: dict[str, Any],
        recent_outcomes: list[dict[str, Any]],
    ) -> tuple[ActionDecision, dict[str, Any] | None]:
        original = decision.model_dump()
        action = decision.action
        target_id = decision.target_id
        target = (action_affordances.get("target_constraints") or {}).get(target_id or "")

        same_failures = [
            outcome
            for outcome in recent_outcomes
            if not outcome.get("success")
            and outcome.get("action") == action
            and outcome.get("target_id") == target_id
        ]
        repeated_inspections = [
            outcome
            for outcome in recent_outcomes
            if outcome.get("success")
            and outcome.get("action") == "inspect"
            and outcome.get("target_id") == target_id
        ]

        replacement: dict[str, Any] | None = None
        correction_reason: str | None = None

        if len(same_failures) >= 2:
            correction_reason = "repeated_recent_failure"
            replacement = {
                "intent": "Break the failed action loop and reassess the current surroundings.",
                "action": "look",
                "target_id": None,
                "direction": None,
                "duration_seconds": 1.0,
            }
        elif action in {"inspect", "pick_up", "eat"}:
            if action == "eat" and target_id is None and action_affordances.get("can_eat_from_inventory"):
                pass
            elif not target or action not in target.get("executable_now", []):
                if target and action in target.get("requires_move_to_for", []):
                    correction_reason = "target_action_requires_approach"
                    replacement = {
                        "intent": f"Move within interaction range of {target_id} before attempting {action}.",
                        "action": "move_to",
                        "target_id": target_id,
                        "direction": target.get("direction"),
                        "duration_seconds": max(1.0, decision.duration_seconds),
                    }
                else:
                    correction_reason = "target_action_not_currently_executable"
                    replacement = {
                        "intent": "Reassess because the proposed target is unavailable, depleted, or incompatible with the action.",
                        "action": "look",
                        "target_id": None,
                        "direction": None,
                        "duration_seconds": 1.0,
                    }
        elif action == "move_to" and target_id:
            if target is None and target_id not in self.agent.known_locations:
                correction_reason = "move_target_not_currently_known"
                replacement = {
                    "intent": "Reassess because the proposed destination is no longer visible or known.",
                    "action": "look",
                    "target_id": None,
                    "direction": None,
                    "duration_seconds": 1.0,
                }
            elif target and target.get("approach_action") is None:
                executable = target.get("executable_now", [])
                preferred = next((name for name in ("pick_up", "eat", "inspect") if name in executable), None)
                correction_reason = "target_already_within_interaction_range"
                if preferred:
                    replacement = {
                        "intent": f"Interact with {target_id}, which is already within range.",
                        "action": preferred,
                        "target_id": target_id,
                        "direction": target.get("direction"),
                        "duration_seconds": max(0.5, decision.duration_seconds),
                    }
                else:
                    replacement = {
                        "intent": "Reassess instead of repeating a no-op approach.",
                        "action": "look",
                        "target_id": None,
                        "direction": None,
                        "duration_seconds": 1.0,
                    }
        elif action == "inspect" and target_id and len(repeated_inspections) >= 2:
            correction_reason = "repeated_inspection_without_new_evidence"
            replacement = {
                "intent": "Stop repeating the same inspection and survey for a new opportunity.",
                "action": "look",
                "target_id": None,
                "direction": None,
                "duration_seconds": 1.0,
            }

        if replacement is None:
            return decision, None

        replacement.update(
            {
                "reason": f"Deterministic correction: {correction_reason}.",
                "plan": [],
                "belief_updates": {},
                "memory_write": None,
            }
        )
        corrected = decision.model_copy(update=replacement)
        return corrected, {
            "reason": correction_reason,
            "original_decision": original,
            "executed_decision": corrected.model_dump(),
        }

    def _verified_memory_request_from(
        self,
        pending: dict[str, Any],
        result: ActionResult,
        action_event_id: int,
    ) -> MemoryWrite:
        candidate = pending["candidate"]
        decision = pending["decision"]
        target = decision.get("target_id") or "current situation"
        tags = list(candidate.get("tags", [])) + ["verified-outcome", result.action.replace("_", "-")]
        content = (
            f"Authoritative outcome: {result.details}\n\n"
            f"Action: {result.action}\n"
            f"Target: {target}\n"
            f"Intent at decision time: {decision.get('intent', '')}\n"
            f"Outcome reason: {result.reason}\n"
            f"Run ID: {self.run_id}\n"
            f"World generation ID: {self.world_generation_id}\n"
            f"Source decision event ID: {pending['decision_event_id']}\n"
            f"Source action-result event ID: {action_event_id}"
        )
        return MemoryWrite(
            category=candidate["category"],
            title=f"Verified {result.action.replace('_', ' ')} outcome: {target}"[:120],
            content=content,
            importance=float(candidate.get("importance", 0.5)),
            tags=tags,
        )

    def _memory_candidate_policy(self, decision) -> tuple[bool, str]:
        candidate = decision.memory_write
        if candidate is None:
            return False, "no_candidate"
        if candidate.importance < 0.65:
            return False, "importance_below_0.65"
        routine_actions = {"move", "move_to", "look", "wait", "rest", "speak"}
        if decision.action in routine_actions:
            return False, "routine_action_not_durable"
        if decision.action == "inspect" and candidate.importance < 0.75:
            return False, "inspection_memory_requires_0.75_importance"
        return True, "eligible_pending_outcome"

    async def make_decision(self) -> None:
        if not self.agent.alive or self.controller.execution or self.agent.sleeping:
            return
        due_consolidation = next(
            (event for event in self.agent.recent_events[-4:] if event.get("kind") == "consolidation_due"),
            None,
        )
        if due_consolidation:
            await self._consolidate("wake")
            self.agent.recent_events = [
                event for event in self.agent.recent_events if event.get("kind") != "consolidation_due"
            ]

        perception = build_perception(self.world, self.agent)
        action_affordances = build_action_affordances(self.world, self.agent, perception)
        recent_outcomes = self._recent_action_outcomes(limit=8)
        action_affordances["recent_authoritative_outcomes"] = recent_outcomes
        action_affordances["blocked_recent_failures"] = [
            {
                "action": outcome.get("action"),
                "target_id": outcome.get("target_id"),
                "reason": outcome.get("reason"),
            }
            for outcome in recent_outcomes
            if not outcome.get("success")
        ]

        query_parts = [self.agent.current_intention]
        query_parts.extend(obj["kind"] for obj in perception["visible_objects"][:8])
        query_parts.extend(entity["classification"] for entity in perception["visible_entities"][:5])
        tags = {item for item in self.agent.inventory}
        memories = retrieve_memories(
            self.vault.list_records(),
            " ".join(query_parts),
            tags=tags,
            sim_time=self.world.sim_time,
            limit=6,
        )
        self.agent.retrieved_memories = memories
        context = {
            "perception": perception,
            "action_affordances": action_affordances,
            "active_plan": self.agent.active_plan,
            "retrieved_memories": memories,
            "recent_outcomes": recent_outcomes,
        }
        result = await self.brain.decide(context)
        model_response_id = self.database.add_model_response(self.world.sim_time, result)
        proposed_decision = result.value
        decision, correction = self._correct_decision(proposed_decision, action_affordances, recent_outcomes)
        self.agent.decision_source = result.source
        if correction:
            self._record(
                "decision_corrected",
                f"Controller corrected {proposed_decision.action} to {decision.action}: {correction['reason']}.",
                0.65,
                correction,
            )
        if decision.plan:
            self.agent.active_plan = [step.strip()[:240] for step in decision.plan if step.strip()]
        elif correction:
            self.agent.active_plan = []
        for key, value in decision.belief_updates.items():
            safe_key = key.strip()[:100]
            safe_value = value.strip()[:500]
            if safe_key and safe_value:
                self.agent.beliefs[safe_key] = safe_value
        self.last_decision = decision.model_dump()
        provider = {
            "finish_reason": getattr(result, "finish_reason", None),
            "provider_response_id": getattr(result, "provider_response_id", None),
            "request_attempts": getattr(result, "request_attempts", None),
            "latency_ms": result.latency_ms,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }
        decision_event = self._record(
            "decision",
            f"Ari chose {decision.action}: {decision.reason}",
            0.55,
            {
                "source": result.source,
                "decision": self.last_decision,
                "proposed_decision": proposed_decision.model_dump() if correction else None,
                "correction": correction,
                "status": result.status,
                "error": result.error,
                "model_response_id": model_response_id,
                "provider": provider,
                "action_affordances": action_affordances,
            },
        )

        self.pending_memory = None
        eligible, policy_reason = self._memory_candidate_policy(decision)
        if decision.memory_write and eligible:
            self.pending_memory = {
                "candidate": decision.memory_write.model_dump(),
                "decision_event_id": decision_event["id"],
                "model_response_id": model_response_id,
                "decision": self.last_decision,
                "run_id": self.run_id,
                "world_generation_id": self.world_generation_id,
                "policy_reason": policy_reason,
            }
            self._record(
                "memory_candidate",
                f"Ari proposed a durable memory pending outcome verification: {decision.memory_write.title}",
                0.35,
                self.pending_memory,
            )
        elif decision.memory_write:
            self._record(
                "memory_candidate_rejected",
                f"Memory candidate filtered before execution: {policy_reason}.",
                0.3,
                {
                    "reason": policy_reason,
                    "candidate": decision.memory_write.model_dump(),
                    "decision_event_id": decision_event["id"],
                },
            )

        action_result = self.controller.start(decision, self.world, self.agent)
        self._handle_action_result(action_result)
        self._decision_pending = not action_result.success
        if action_result.success and decision.action == "sleep":
            await self._consolidate("sleep_start")

    def _resolve_pending_memory(self, result: ActionResult, action_event: dict[str, Any]) -> None:
        if result.reason == "started" or not self.pending_memory:
            return
        pending = self.pending_memory
        self.pending_memory = None
        if not result.success:
            self._record(
                "memory_rejected",
                "Proposed memory rejected because the authoritative action outcome was unsuccessful.",
                0.65,
                {
                    "reason": "action_outcome_not_successful",
                    "candidate": pending["candidate"],
                    "action_result": result.to_dict(),
                    "decision_event_id": pending["decision_event_id"],
                    "action_result_event_id": action_event["id"],
                },
            )
            return

        request = self._verified_memory_request_from(pending, result, action_event["id"])
        try:
            record = self.vault.write(request, self.world.sim_time)
            self.database.add_memory(record)
            payload = record.to_dict()
            payload["provenance"] = {
                "run_id": self.run_id,
                "world_generation_id": self.world_generation_id,
                "decision_event_id": pending["decision_event_id"],
                "action_result_event_id": action_event["id"],
                "model_response_id": pending["model_response_id"],
            }
            self.memory_writes.append(payload)
            self._record("memory_write", f"Ari wrote verified memory: {record.title}", 0.65, payload)
        except MemoryValidationError as exc:
            self._record(
                "memory_rejected",
                f"Verified memory write rejected: {exc}",
                0.6,
                {
                    "request": request.model_dump(),
                    "reason": str(exc),
                    "decision_event_id": pending["decision_event_id"],
                    "action_result_event_id": action_event["id"],
                },
            )
