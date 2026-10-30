from fastapi import WebSocket

from app.live.push import notify_seller_devices
from app.live.schemas.event import LiveNotificationEvent
from app.notifications.schemas import SellerNotificationPublic


class LiveHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}

    async def connect(self, seller_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sockets.setdefault(seller_id, set()).add(websocket)

    def disconnect(self, seller_id: str, websocket: WebSocket) -> None:
        sockets = self._sockets.get(seller_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._sockets.pop(seller_id, None)

    async def send(self, seller_id: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        for websocket in list(self._sockets.get(seller_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(seller_id, websocket)


hub = LiveHub()


async def publish_seller_data_update(seller_id: str, *resources: str) -> None:
    """Notifica a todas las sesiones abiertas del vendedor que refresquen sus datos."""
    try:
        from app.database import get_orders_collection

        pending_count = await get_orders_collection().count_documents(
            {"seller_id": str(seller_id), "status": "pending_confirmation"}
        )
        await hub.send(str(seller_id), {
            "type": "seller_data_update",
            "resources": list(resources),
            "pending_order_count": pending_count,
        })
    except Exception:
        return


async def publish_seller_notification(
    seller_id: str,
    notification: SellerNotificationPublic,
) -> None:
    try:
        event = LiveNotificationEvent(notification=notification)
        await hub.send(str(seller_id), event.model_dump(mode="json"))
        await notify_seller_devices(str(seller_id), notification.title, notification.content)
    except Exception:
        return
