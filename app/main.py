from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, load_settings
from app.simulation.scheduler import SimulationEngine
from app.updater.manager import UpdateManager
from app.version import __version__
from app.web.routes import router as api_router
from app.web.websocket import router as websocket_router

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"


def create_app(
    settings: Settings | None = None,
    *,
    engine: SimulationEngine | None = None,
    updater: UpdateManager | None = None,
    start_background: bool = True,
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    resolved_engine = engine or SimulationEngine(resolved_settings)
    resolved_updater = updater or UpdateManager(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = resolved_engine
        app.state.updater = resolved_updater
        if start_background:
            await resolved_engine.start()
            await resolved_updater.start()
        try:
            yield
        finally:
            await resolved_updater.stop()
            if start_background:
                await resolved_engine.stop()

    app = FastAPI(
        title="Embodied Artificial Life",
        version=__version__,
        description="Local deterministic artificial-life experiment with an optional OpenAI-compatible brain.",
        lifespan=lifespan,
    )
    app.state.engine = resolved_engine
    app.state.updater = resolved_updater
    app.state.shutdown_callback = shutdown_callback
    app.include_router(api_router)
    app.include_router(websocket_router)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "templates" / "index.html")

    return app
