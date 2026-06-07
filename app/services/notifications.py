import uuid
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.database import get_notifications_collection, get_orders_collection, get_registrations_collection
from app.schemas.notifications import (
    AdminNotificationBroadcastPublic,
    AdminNotificationSendResult,
    SellerNotificationPublic,
    SellerNotificationUnreadCount,
)
from app.services.subscriptions import (
    ACTION_RENEW_SUBSCRIPTION,
    NOTIFICATION_KIND_EXPIRING,
    is_subscription_active,
    is_within_warning_window,
    subscription_days_remaining,
    warning_notification_content,
)
from app.utils.datetime import to_utc_naive, utc_now

NOTIFICATION_KIND_NEW_ORDER = "new_order"
ACTION_VIEW_ORDERS = "view_orders"


async def ensure_notification_indexes() -> None:
    collection = get_notifications_collection()
    await collection.create_index([("seller_id", ASCENDING), ("created_at", DESCENDING)])
    await collection.create_index([("seller_id", ASCENDING), ("read_at", ASCENDING)])
    await collection.create_index([("batch_id", ASCENDING), ("created_at", DESCENDING)])
    await collection.create_index(
        [("seller_id", ASCENDING), ("kind", ASCENDING), ("subscription_ends_at", ASCENDING)],
        unique=True,
        partialFilterExpression={"kind": NOTIFICATION_KIND_EXPIRING},
    )


def _document_to_public(doc: dict[str, Any]) -> SellerNotificationPublic:
    return SellerNotificationPublic(
        id=str(doc["_id"]),
        title=doc["title"],
        content=doc["content"],
        read_at=doc.get("read_at"),
        created_at=doc["created_at"],
        kind=doc.get("kind"),
        action_label=doc.get("action_label"),
        action_type=doc.get("action_type"),
    )


async def ensure_subscription_expiring_notifications() -> int:
    registrations = get_registrations_collection()
    notifications = get_notifications_collection()
    now = utc_now()
    created = 0

    cursor = registrations.find(
        {
            "status": "approved",
            "subscription_ends_at": {"$ne": None},
        },
        {"_id": 1, "subscription_ends_at": 1},
    )

    async for doc in cursor:
        if not is_within_warning_window(doc, now=now):
            continue

        ends_at = doc["subscription_ends_at"]
        days_remaining = subscription_days_remaining(doc, now=now)
        if days_remaining is None or days_remaining <= 0:
            continue

        existing = await notifications.find_one(
            {
                "seller_id": doc["_id"],
                "kind": NOTIFICATION_KIND_EXPIRING,
                "subscription_ends_at": ends_at,
            },
        )
        if existing:
            continue

        await notifications.insert_one(
            {
                "seller_id": doc["_id"],
                "batch_id": f"subscription-expiring-{doc['_id']}-{ends_at.isoformat()}",
                "kind": NOTIFICATION_KIND_EXPIRING,
                "subscription_ends_at": ends_at,
                "title": "Tu suscripción vence pronto",
                "content": warning_notification_content(days_remaining),
                "action_label": "Renovar plan",
                "action_type": ACTION_RENEW_SUBSCRIPTION,
                "read_at": None,
                "created_at": to_utc_naive(now),
                "created_by_admin_id": None,
            },
        )
        created += 1

    return created


async def ensure_pending_order_notifications() -> int:
    """Crea notificaciones faltantes para pedidos pendientes ya guardados."""
    orders = get_orders_collection()
    notifications = get_notifications_collection()
    created = 0

    cursor = orders.find({"status": "pending_confirmation"})
    async for order in cursor:
        order_oid = order["_id"]
        existing = await notifications.find_one(
            {
                "kind": NOTIFICATION_KIND_NEW_ORDER,
                "order_id": str(order_oid),
            },
        )
        if existing:
            continue

        try:
            seller_oid = ObjectId(str(order["seller_id"]))
        except Exception:
            continue

        item_count = sum(int(item.get("quantity", 0)) for item in order.get("items") or [])
        await notify_seller_new_order(
            seller_oid,
            order_oid,
            item_count=item_count,
            delivery_requested=bool(order.get("delivery_requested")),
        )
        created += 1

    return created


async def notify_seller_new_order(
    seller_id: str | ObjectId,
    order_id: str | ObjectId,
    *,
    item_count: int,
    delivery_requested: bool,
) -> None:
    try:
        seller_object_id = seller_id if isinstance(seller_id, ObjectId) else ObjectId(str(seller_id))
        order_object_id = order_id if isinstance(order_id, ObjectId) else ObjectId(str(order_id))
    except Exception:
        return

    order_code = str(order_object_id)[-6:].upper()
    product_label = "producto" if item_count == 1 else "productos"
    content_lines = [
        f"Pedido #{order_code} desde Pa' La Jaba.",
        f"{item_count} {product_label} por confirmar.",
    ]
    if delivery_requested:
        content_lines.append("El cliente solicitó entrega a domicilio.")

    collection = get_notifications_collection()
    await collection.insert_one(
        {
            "seller_id": seller_object_id,
            "batch_id": f"new-order-{order_object_id}",
            "kind": NOTIFICATION_KIND_NEW_ORDER,
            "order_id": str(order_object_id),
            "title": "Nuevo pedido recibido",
            "content": "\n".join(content_lines),
            "action_label": "Ver pedidos",
            "action_type": ACTION_VIEW_ORDERS,
            "read_at": None,
            "created_at": to_utc_naive(utc_now()),
            "created_by_admin_id": None,
        },
    )


async def send_notification_to_sellers(
    admin_id: str,
    title: str,
    content: str,
) -> AdminNotificationSendResult:
    registrations = get_registrations_collection()
    sellers = await registrations.find({"status": "approved"}, {"_id": 1, "subscription_ends_at": 1, "status": 1}).to_list(length=None)
    sellers = [seller for seller in sellers if is_subscription_active(seller)]

    if not sellers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay vendedores activos para recibir la notificación.",
        )

    now = to_utc_naive(utc_now())
    batch_id = uuid.uuid4().hex
    title_clean = title.strip()
    content_clean = content.strip()

    try:
        admin_object_id = ObjectId(admin_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin no válido.",
        ) from exc

    documents = [
        {
            "seller_id": seller["_id"],
            "batch_id": batch_id,
            "title": title_clean,
            "content": content_clean,
            "read_at": None,
            "created_at": now,
            "created_by_admin_id": admin_object_id,
        }
        for seller in sellers
    ]

    collection = get_notifications_collection()
    await collection.insert_many(documents)

    return AdminNotificationSendResult(
        batch_id=batch_id,
        title=title_clean,
        content=content_clean,
        recipient_count=len(documents),
        created_at=now,
    )


async def list_admin_broadcasts(limit: int = 30) -> list[AdminNotificationBroadcastPublic]:
    collection = get_notifications_collection()
    pipeline = [
        {"$sort": {"created_at": DESCENDING}},
        {
            "$group": {
                "_id": "$batch_id",
                "title": {"$first": "$title"},
                "content": {"$first": "$content"},
                "created_at": {"$first": "$created_at"},
                "recipient_count": {"$sum": 1},
            }
        },
        {"$sort": {"created_at": DESCENDING}},
        {"$limit": limit},
    ]
    rows = await collection.aggregate(pipeline).to_list(length=limit)
    return [
        AdminNotificationBroadcastPublic(
            batch_id=row["_id"],
            title=row["title"],
            content=row["content"],
            recipient_count=row["recipient_count"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def list_seller_notifications(
    seller_id: str,
    limit: int = 50,
) -> list[SellerNotificationPublic]:
    await ensure_subscription_expiring_notifications()

    try:
        seller_object_id = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        ) from exc

    collection = get_notifications_collection()
    cursor = collection.find({"seller_id": seller_object_id}).sort("created_at", DESCENDING).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [_document_to_public(doc) for doc in docs]


async def get_unread_count(seller_id: str) -> SellerNotificationUnreadCount:
    await ensure_subscription_expiring_notifications()

    try:
        seller_object_id = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        ) from exc

    collection = get_notifications_collection()
    count = await collection.count_documents(
        {"seller_id": seller_object_id, "read_at": None},
    )
    return SellerNotificationUnreadCount(count=count)


async def mark_notification_read(
    seller_id: str,
    notification_id: str,
) -> SellerNotificationPublic:
    try:
        seller_object_id = ObjectId(seller_id)
        notification_object_id = ObjectId(notification_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada.",
        ) from exc

    now = to_utc_naive(utc_now())
    collection = get_notifications_collection()
    result = await collection.find_one_and_update(
        {
            "_id": notification_object_id,
            "seller_id": seller_object_id,
            "read_at": None,
        },
        {"$set": {"read_at": now}},
        return_document=ReturnDocument.AFTER,
    )

    if result is None:
        existing = await collection.find_one(
            {"_id": notification_object_id, "seller_id": seller_object_id},
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notificación no encontrada.",
            )
        return _document_to_public(existing)

    return _document_to_public(result)
