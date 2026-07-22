from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.memory.vault import MemoryVault
from app.simulation.scheduler import SimulationEngine
from app.storage.database import Database


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="embodied-alife-smoke-") as temp:
        root = Path(temp)
        settings = Settings(
            data_dir=root / "data",
            world_seed=424242,
            world_size=64,
            no_llm=True,
            sim_start_paused=False,
        )
        database = Database(settings.database_path)
        engine = SimulationEngine(
            settings,
            database=database,
            vault=MemoryVault(settings.memory_dir),
            load_existing=False,
        )
        start = (engine.agent.x, engine.agent.y)
        for _ in range(120):
            await engine.advance(1.0, allow_decision=True)
        summary = {
            "seed": engine.world.seed,
            "sim_time": engine.world.sim_time,
            "start": start,
            "end": (round(engine.agent.x, 2), round(engine.agent.y, 2)),
            "alive": engine.agent.alive,
            "health": round(engine.agent.health, 2),
            "last_decision": engine.last_decision,
            "event_count": len(engine.events),
            "memory_count": len(engine.vault.list_records()),
            "decision_source": engine.agent.decision_source,
        }
        print(summary)
        assert engine.world.sim_time == 120.0
        assert engine.agent.alive
        assert engine.last_decision is not None
        assert engine.agent.decision_source == "fallback"
        database.close()


if __name__ == "__main__":
    asyncio.run(main())
