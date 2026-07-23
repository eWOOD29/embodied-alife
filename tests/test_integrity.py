from __future__ import annotations

from app.llm.client import BrainResult
from app.llm.schemas import ActionDecision, MemoryWrite
from app.memory.vault import MemoryVault
from app.simulation.engine import SimulationEngine
from app.storage.database import Database


class StubBrain:
    def __init__(self, decision: ActionDecision) -> None:
        self.decision = decision
        self.status = {"mode": "llm", "available": True}

    async def decide(self, context):
        return BrainResult(self.decision, "llm", "ok", latency_ms=1.0, prompt_tokens=10, completion_tokens=10)

    async def check_status(self):
        return self.status


def _decision(action: str, *, target_id: str | None = None) -> ActionDecision:
    return ActionDecision(
        intent="Test the authoritative outcome boundary.",
        action=action,
        target_id=target_id,
        direction=None,
        duration_seconds=0.2,
        interrupt_if=[],
        reason="Exercise the integrity path.",
        plan=[],
        belief_updates={},
        memory_write=MemoryWrite(
            category="affordances",
            title="The proposed action succeeded",
            content="This candidate must not be trusted until the world confirms it.",
            importance=0.7,
            tags=["test"],
        ),
    )


async def test_failed_action_does_not_create_durable_memory(settings) -> None:
    database = Database(settings.database_path)
    vault = MemoryVault(settings.memory_dir)
    engine = SimulationEngine(
        settings,
        database=database,
        vault=vault,
        brain=StubBrain(_decision("pick_up", target_id="missing_resource")),
        load_existing=False,
    )
    try:
        await engine.make_decision()
        assert vault.list_records() == []
        assert engine.pending_memory is None
        assert any(event["kind"] == "memory_rejected" for event in engine.events)
    finally:
        database.close()


async def test_successful_action_creates_only_verified_outcome_memory(settings) -> None:
    database = Database(settings.database_path)
    vault = MemoryVault(settings.memory_dir)
    engine = SimulationEngine(
        settings,
        database=database,
        vault=vault,
        brain=StubBrain(_decision("eat")),
        load_existing=False,
    )
    engine.agent.inventory["edible_plant"] = 1
    try:
        await engine.make_decision()
        assert vault.list_records() == []
        await engine.advance(0.3, allow_decision=False)
        records = vault.list_records()
        assert len(records) == 1
        assert records[0].title.startswith("Verified eat outcome")
        assert "Authoritative outcome" in records[0].content
        assert "This candidate must not be trusted" not in records[0].content
    finally:
        database.close()


def test_reset_starts_clean_experiment(engine) -> None:
    old_run_id = engine.run_id
    old_world_generation_id = engine.world_generation_id
    engine.vault.write(
        MemoryWrite(
            category="environment",
            title="Old world memory",
            content="This belongs only to the previous generated world.",
            importance=0.8,
            tags=["old-world"],
        ),
        engine.world.sim_time,
    )
    engine.save_snapshot("old-world")

    result = engine.reset(54321)

    assert result["clean_experiment"] is True
    assert engine.run_id != old_run_id
    assert engine.world_generation_id != old_world_generation_id
    assert engine.vault.list_records() == []
    assert engine.snapshots.list() == []
    assert len(engine.database.list_model_responses()) == 0
    assert [event["kind"] for event in engine.database.list_events()] == ["awakening"]
