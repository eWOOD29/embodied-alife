from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import LocalLLMClient
from app.memory.vault import MemoryRecord, MemoryValidationError, MemoryVault
from app.simulation.agent import AgentState


@dataclass(slots=True)
class ConsolidationOutcome:
    source: str
    summary: str
    written: list[MemoryRecord]
    rejected: list[str]


async def consolidate_sleep(
    brain: LocalLLMClient,
    vault: MemoryVault,
    agent: AgentState,
    *,
    day: int,
    sim_time: float,
    events: list[dict],
) -> ConsolidationOutcome:
    result = await brain.consolidate(
        {
            "day": day,
            "body": agent.to_dict(),
            "events": events,
            "beliefs": agent.beliefs,
            "memories": [record.to_dict() for record in vault.list_records()[-12:]],
        }
    )
    written: list[MemoryRecord] = []
    rejected: list[str] = []
    for request in result.value.memories:
        try:
            written.append(vault.write(request, sim_time))
        except MemoryValidationError as exc:
            rejected.append(str(exc))
    for key, value in result.value.belief_updates.items():
        safe_key = key.strip()[:100]
        safe_value = value.strip()[:500]
        if safe_key and safe_value:
            agent.beliefs[safe_key] = safe_value
    if result.value.next_intention:
        agent.current_intention = result.value.next_intention
    return ConsolidationOutcome(result.source, result.value.summary, written, rejected)
