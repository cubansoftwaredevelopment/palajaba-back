from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from app.live.push import notify_customer_devices, notify_seller_devices
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

    async def broadcast(self, payload: dict) -> None:
        for user_id in list(self._sockets):
            await self.send(user_id, payload)


hub = LiveHub()
customer_hub = LiveHub()


async def publish_app_release_update(release: dict) -> None:
    """Avisa por el hub a las sesiones abiertas que hay una versión principal nueva."""
    payload = {
        "type": "app_release_update",
        "release": jsonable_encoder(release),
    }
    try:
        await hub.broadcast(payload)
        await customer_hub.broadcast(payload)
    except Exception:
        return


async def publish_seller_data_update(seller_id: str, *resources: str) -> None:
    """Notifica a todas las sesiones abiertas del vendedor que refresquen sus datos."""
    try:
        from app.database import get_orders_collection

        from app.orders.constants import OPEN_ORDER_STATUSES
        pending_count = await get_orders_collection().count_documents(
            {"seller_id": str(seller_id), "status": {"$in": list(OPEN_ORDER_STATUSES)}}
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
        await notify_seller_devices(
            str(seller_id),
            notification.title,
            notification.content,
            notification_id=str(getattr(notification, "id", "") or ""),
            kind=str(getattr(notification, "kind", "") or ""),
        )
    except Exception:
        return


async def publish_customer_notification(customer_id: str, notification: dict) -> None:
    """Entrega avisos del comprador por WebSocket y Google Firebase Push."""
    try:
        await customer_hub.send(str(customer_id), {
            "type": "customer_notification",
            "notification": jsonable_encoder(notification),
        })
    except Exception:
        pass
    kind = str(notification.get("kind") or "")
    store_name = str(notification.get("store_name") or "").strip()
    title = str(notification.get("title") or "").strip() or "Aviso"
    content = str(notification.get("content") or "").strip()
    if kind == "store" and store_name:
        push_title = store_name
        push_body = f"{title}. {content}" if title and content and content != title else (content or title)
    else:
        push_title = title
        push_body = content or "Tienes una novedad en Pa' La Jaba."
    try:
        await notify_customer_devices(
            str(customer_id),
            push_title,
            push_body,
            order_id=str(notification["order_id"]) if notification.get("order_id") else None,
            notification_id=str(notification.get("id") or ""),
            kind=kind,
            store_name=store_name or None,
        )
    except Exception:
        return
