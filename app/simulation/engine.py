from __future__ import annotations

from typing import Any

from app.llm.schemas import MemoryWrite
from app.memory.vault import MemoryValidationError
from app.simulation.actions import ActionResult
from app.simulation.scheduler import SimulationEngine as BaseSimulationEngine


class SimulationEngine(BaseSimulationEngine):
    """Production engine with authoritative outcome-verified memory commits.

    The base scheduler owns deterministic simulation timing and persistence. This layer
    keeps proposed LLM memories pending until the matching action has reached a final
    authoritative outcome.
    """

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
