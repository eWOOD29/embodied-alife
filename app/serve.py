from __future__ import annotations

import uvicorn

from app.config import load_settings
from app.main import create_app


def main() -> None:
    """Launch Uvicorn using project settings loaded from .env."""
    settings = load_settings()
    server_holder: dict[str, uvicorn.Server] = {}

    def request_shutdown() -> None:
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True

    application = create_app(settings, shutdown_callback=request_shutdown)
    config = uvicorn.Config(
        application,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server_holder["server"] = server
    server.run()


if __name__ == "__main__":
    main()
