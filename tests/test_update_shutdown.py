from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.web.websocket import simulation_socket


class FakeEngine:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.unsubscribed = False

    async def subscribe(self) -> asyncio.Queue:
        return self.queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        assert queue is self.queue
        self.unsubscribed = True


class FakeWebSocket:
    def __init__(self, engine: FakeEngine) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(engine=engine, shutting_down=True)
        )
        self.accepted = False
        self.closed: tuple[int, str] | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, *, code: int, reason: str) -> None:
        self.closed = (code, reason)

    async def send_json(self, state: dict) -> None:
        raise AssertionError(f"state should not be sent during shutdown: {state}")


@pytest.mark.asyncio
async def test_websocket_closes_immediately_for_update_shutdown() -> None:
    engine = FakeEngine()
    websocket = FakeWebSocket(engine)

    await simulation_socket(websocket)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.closed == (1012, "application update")
    assert engine.unsubscribed is True


def test_server_has_bounded_graceful_shutdown() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "serve.py"
    ).read_text(encoding="utf-8")
    assert "timeout_graceful_shutdown=5" in source
    assert "application.state.shutting_down = True" in source
