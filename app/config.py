from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8797
    data_dir: Path = Path("data")
    world_seed: int = 20260722
    world_size: int = 128
    sim_tick_seconds: float = 0.2
    sim_start_paused: bool = False
    sim_speed: int = 1
    no_llm: bool = False
    llm_base_url: str = "http://127.0.0.1:1234/v1"
    llm_api_key: str = "***"
    llm_model: str = ""
    llm_context_length: int = 16384
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.3
    llm_max_tokens: int = 900
    update_enabled: bool = True
    update_repository: str = "eWOOD29/embodied-alife"
    update_channel: str = "stable"
    update_asset_name: str = "embodied-alife-update.zip"
    update_check_on_startup: bool = True
    update_startup_delay_seconds: float = 5.0
    update_check_interval_hours: float = 6.0
    update_timeout_seconds: float = 30.0
    update_max_download_bytes: int = 100 * 1024 * 1024
    update_max_extract_bytes: int = 250 * 1024 * 1024
    update_max_release_notes_chars: int = 12000
    update_auto_restart: bool = True
    update_github_token: str = ""

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "agent_memory"

    @property
    def database_path(self) -> Path:
        return self.runtime_dir / "embodied_alife.db"


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(env_file: str | Path | None = None) -> Settings:
    load_dotenv(dotenv_path=env_file, override=False)
    settings = Settings(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8797")),
        data_dir=Path(os.getenv("DATA_DIR", "data")),
        world_seed=int(os.getenv("WORLD_SEED", "20260722")),
        world_size=max(32, min(256, int(os.getenv("WORLD_SIZE", "128")))),
        sim_tick_seconds=max(0.05, float(os.getenv("SIM_TICK_SECONDS", "0.2"))),
        sim_start_paused=_bool("SIM_START_PAUSED", False),
        sim_speed=int(os.getenv("SIM_SPEED", "1")),
        no_llm=_bool("NO_LLM", False),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/"),
        llm_api_key=os.getenv("LLM_API_KEY", "***"),
        llm_model=os.getenv("LLM_MODEL", "").strip(),
        llm_context_length=int(os.getenv("LLM_CONTEXT_LENGTH", "16384")),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "900")),
        update_enabled=_bool("UPDATE_ENABLED", True),
        update_repository=os.getenv("UPDATE_REPOSITORY", "eWOOD29/embodied-alife").strip(),
        update_channel=os.getenv("UPDATE_CHANNEL", "stable").strip().lower(),
        update_asset_name=os.getenv("UPDATE_ASSET_NAME", "embodied-alife-update.zip").strip(),
        update_check_on_startup=_bool("UPDATE_CHECK_ON_STARTUP", True),
        update_startup_delay_seconds=max(0.0, float(os.getenv("UPDATE_STARTUP_DELAY_SECONDS", "5"))),
        update_check_interval_hours=max(1.0, float(os.getenv("UPDATE_CHECK_INTERVAL_HOURS", "6"))),
        update_timeout_seconds=max(5.0, float(os.getenv("UPDATE_TIMEOUT_SECONDS", "30"))),
        update_max_download_bytes=max(1_000_000, int(os.getenv("UPDATE_MAX_DOWNLOAD_BYTES", str(100 * 1024 * 1024)))),
        update_max_extract_bytes=max(1_000_000, int(os.getenv("UPDATE_MAX_EXTRACT_BYTES", str(250 * 1024 * 1024)))),
        update_max_release_notes_chars=max(1000, int(os.getenv("UPDATE_MAX_RELEASE_NOTES_CHARS", "12000"))),
        update_auto_restart=_bool("UPDATE_AUTO_RESTART", True),
        update_github_token=os.getenv("UPDATE_GITHUB_TOKEN", "").strip(),
    )
    if settings.update_channel not in {"stable", "prerelease"}:
        settings.update_channel = "stable"
    if settings.sim_speed not in {1, 10, 100}:
        settings.sim_speed = 1
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    return settings
