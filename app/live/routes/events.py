from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.live.hub import customer_hub, hub
from app.live.utils import customer_id_from_access_token, seller_id_from_access_token

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
        from app.database import get_orders_collection
        pending_count = await get_orders_collection().count_documents(
            {"seller_id": seller_id, "status": "pending_confirmation"}
        )
        await websocket.send_json({
            "type": "seller_data_update",
            "resources": [],
            "pending_order_count": pending_count,
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(seller_id, websocket)


@router.websocket("/customer-events")
async def customer_events(websocket: WebSocket, token: str = Query(default="")):
    try:
        customer_id = await customer_id_from_access_token(token)
    except Exception:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await customer_hub.connect(customer_id, websocket)
    try:
        await websocket.send_json({"type": "customer_data_update", "resources": ["orders"]})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        customer_hub.disconnect(customer_id, websocket)
