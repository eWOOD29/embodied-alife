from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import LocalLLMClient
from app.memory.vault import MemoryRecord, MemoryValidationError, MemoryVault
from app.simulation.agent import AgentState
from app.simulation.integrity import (
    agent_key,
    seal_memory_record,
    seal_record,
    verify_memory_record,
    verify_record,
)


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
    key = agent_key(agent)
    runtime_dir = vault.root.parent / "runtime"
    verified_beliefs = {
        belief_id: belief
        for belief_id, belief in (agent.beliefs.items() if isinstance(agent.beliefs, dict) else [])
        if verify_record("belief", belief, agent)
    }
    verified_memories = [
        record.to_dict()
        for record in vault.list_records()
        if verify_memory_record(runtime_dir, record, key)
    ][-12:]
    result = await brain.consolidate(
        {
            "day": day,
            "body": agent.to_dict(),
            "events": events,
            "beliefs": verified_beliefs,
            "memories": verified_memories,
        }
    )
    written: list[MemoryRecord] = []
    rejected: list[str] = []
    for request in result.value.memories:
        try:
            record = vault.write(request, sim_time)
            if seal_memory_record(
                runtime_dir,
                record,
                key,
                "validated_consolidation",
                source_ref=f"consolidation:{sim_time:.3f}:{record.id}",
            ):
                written.append(record)
            else:
                rejected.append("memory_integrity_proof_failed")
        except MemoryValidationError as exc:
            rejected.append(str(exc))
    for raw_key, raw_value in result.value.belief_updates.items():
        safe_key = raw_key.strip()[:100]
        safe_value = raw_value.strip()[:500]
        if safe_key and safe_value:
            agent.beliefs[safe_key] = safe_value
            belief = agent.beliefs.get(safe_key)
            if isinstance(belief, dict):
                belief["source_type"] = "reflection"
                provenance = belief.get("provenance")
                if isinstance(provenance, dict):
                    provenance["source_type"] = "reflection"
            seal_record(
                "belief",
                belief,
                key,
                "validated_consolidation",
                source_type="reflection",
                source_ref=f"consolidation:{sim_time:.3f}:{safe_key}",
            )
    if result.value.next_intention:
        agent.current_intention = result.value.next_intention
    return ConsolidationOutcome(result.source, result.value.summary, written, rejected)
