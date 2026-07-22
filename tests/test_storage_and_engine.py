from __future__ import annotations

import pytest


def test_snapshot_save_load(engine) -> None:
    original_seed = engine.world.seed
    engine.agent.health = 73
    engine.world.sim_time = 88
    engine.save_snapshot("checkpoint")
    engine.agent.health = 12
    engine.world.sim_time = 200
    loaded = engine.load_snapshot("checkpoint")
    assert loaded["ok"]
    assert engine.agent.health == 73
    assert engine.world.sim_time == 88
    assert engine.world.seed == original_seed
    assert engine.paused


def test_runtime_state_roundtrip(engine) -> None:
    state = engine.serialize()
    engine.agent.beliefs["test"] = "changed"
    engine._restore(state)
    assert "test" not in engine.agent.beliefs
    assert engine.world.seed == state["world"]["seed"]


@pytest.mark.asyncio
async def test_short_fallback_simulation_moves_or_acts(engine) -> None:
    engine.paused = False
    start = (engine.agent.x, engine.agent.y)
    for _ in range(30):
        await engine.advance(1.0, allow_decision=True)
    assert engine.world.sim_time >= 30
    assert engine.last_decision is not None
    assert engine.last_action_result is not None
    assert (engine.agent.x, engine.agent.y) != start or engine.events
    assert engine.agent.decision_source == "fallback"

@pytest.mark.asyncio
async def test_sleep_triggers_memory_consolidation(engine) -> None:
    engine.agent.sleep_pressure = 95
    engine.agent.energy = 12
    await engine.make_decision()
    assert engine.last_decision["action"] == "sleep"
    assert engine.agent.sleeping
    assert any(event["kind"] == "consolidation" for event in engine.events)
    assert engine.vault.list_records()


def test_database_retry_handles_transient_lock(engine) -> None:
    import sqlite3

    calls = {"count": 0}

    def operation():
        calls["count"] += 1
        if calls["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert engine.database._retry(operation) == "ok"
    assert calls["count"] == 3
