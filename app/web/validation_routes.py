from __future__ import annotations

from fastapi import APIRouter, Request

from app.diagnostics import build_diagnostic_bundle
from app.version import __version__

router = APIRouter()


@router.get("/api/validation/readiness")
def validation_readiness(request: Request) -> dict:
    engine = request.app.state.engine
    updater = request.app.state.updater
    health = {
        "status": "ok",
        "version": __version__,
        "run_id": getattr(engine, "run_id", None),
        "world_generation_id": getattr(engine, "world_generation_id", None),
        "paused": engine.paused,
        "alive": engine.agent.alive,
        "seed": engine.world.seed,
        "sim_time": round(engine.world.sim_time, 2),
    }
    bundle = build_diagnostic_bundle(
        engine=engine,
        updater=updater,
        health=health,
        application_version=__version__,
    )
    return bundle["soak_readiness"]
