from __future__ import annotations

import uvicorn

from app.config import load_settings
from app.main import create_app


def main() -> None:
    """Launch Uvicorn using project settings loaded from .env."""
    settings = load_settings()
    server_holder: dict[str, uvicorn.Server] = {}
    application = None

    def request_shutdown() -> None:
        if application is not None:
            application.state.shutting_down = True
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True

    application = create_app(settings, shutdown_callback=request_shutdown)
    application.state.shutting_down = False
    config = uvicorn.Config(
        application,
        host=settings.host,
        port=settings.port,
        log_level="info",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    server_holder["server"] = server
    server.run()


if __name__ == "__main__":
    main()
