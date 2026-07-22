from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def simulation_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    engine = websocket.app.state.engine
    queue = await engine.subscribe()
    try:
        while True:
            state = await queue.get()
            await websocket.send_json(state)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.unsubscribe(queue)
