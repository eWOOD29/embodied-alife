from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.serialization import json_safe

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
            await websocket.send_json(json_safe(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=250000, max_source_items=300000))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.unsubscribe(queue)
