from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.memory.vault import MemoryVault
from app.simulation.scheduler import SimulationEngine
from app.storage.database import Database


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        world_seed=12345,
        world_size=48,
        no_llm=True,
        sim_start_paused=True,
        sim_tick_seconds=0.1,
    )


@pytest.fixture
def engine(settings: Settings) -> SimulationEngine:
    database = Database(settings.database_path)
    vault = MemoryVault(settings.memory_dir)
    sim = SimulationEngine(settings, database=database, vault=vault, load_existing=False)
    yield sim
    database.close()
