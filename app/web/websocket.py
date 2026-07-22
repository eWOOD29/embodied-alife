from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def simulation_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    engine = websocket.app.state.engine
    queue = await engine.subscribe()
    try:
        while True:
            if getattr(websocket.app.state, "shutting_down", False):
                await websocket.close(code=1012, reason="application update")
                break
            try:
                state = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            await websocket.send_json(state)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.unsubscribe(queue)
