from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.live.hub import hub
from app.live.utils import seller_id_from_access_token

router = APIRouter()


@router.websocket("/events")
async def seller_events(websocket: WebSocket, token: str = Query(default="")):
    try:
        seller_id = await seller_id_from_access_token(token)
    except Exception:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await hub.connect(seller_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(seller_id, websocket)
