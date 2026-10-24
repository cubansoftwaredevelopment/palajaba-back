import asyncio
import logging
import uuid
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.database import get_notifications_collection, get_orders_collection, get_registrations_collection
from app.live.hub import publish_seller_notification
from app.notifications.otp_manager import send_custom_sms, send_sms_campaign
from app.auth.registrations import phone_e164
from app.notifications.schemas import (
    AdminNotificationBroadcastPublic,
    AdminNotificationSendEvent,
    AdminNotificationSendResult,
    NotificationAudienceInput,
    SellerNotificationBulkReadResult,
    SellerNotificationPublic,
    SellerNotificationUnreadCount,
)
from app.subscriptions.service import (
    PREMIUM_PLAN_TIER,
    PRO_PLAN_TIER,
    STANDARD_PLAN_TIER,
    normalize_billing_period,
    normalize_plan_tier,
)
from app.subscriptions.service import (
    ACTION_RENEW_SUBSCRIPTION,
    EXPIRY_NOTICE_FOR_FIELD,
    EXPIRY_NOTICE_SMS_FIELD,
    NOTIFICATION_KIND_EXPIRING,
    contact_reminder_content,
    expiry_notice_channel_state,
    expiry_notice_title,
    is_subscription_active,
    is_within_contact_reminder_window,
    is_within_warning_window,
    subscription_days_remaining,
    warning_notification_content,
)
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)

NOTIFICATION_KIND_NEW_ORDER = "new_order"
ACTION_VIEW_ORDERS = "view_orders"
SUBSCRIPTION_REMINDER_POLL_SECONDS = 1800

_reminder_task: asyncio.Task | None = None


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


def _is_admin_notification(doc: dict[str, Any]) -> bool:
    return isinstance(doc.get("created_by_admin_id"), ObjectId)


def _channel_error_message(detail: Any, fallback: str) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(detail, dict):
        for key in ("message", "detail", "error"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _sms_error_message(detail: Any) -> str:
    return _channel_error_message(detail, "No pudimos enviar el SMS del aviso.")


def _system_notifications_filter(seller_object_id: ObjectId) -> dict[str, Any]:
    return {
        "seller_id": seller_object_id,
        "read_at": None,
        "created_by_admin_id": {"$not": {"$type": "objectId"}},
    }


def _seller_phone_e164(seller: dict[str, Any]) -> str | None:
    digits = "".join(ch for ch in str(seller.get("phone") or "") if ch.isdigit())
    if digits.startswith("53") and len(digits) == 10:
        digits = digits[2:]
    if len(digits) != 8:
        return None
    return phone_e164(digits)


async def _deliver_contact_channel(send) -> str:
    try:
        await send()
        return "sent"
    except HTTPException as exc:
        logger.warning("Aviso de vencimiento por OTP falló: %s", exc.detail)
        if exc.status_code in (429, 503, 402):
            return "retry"
        return "skipped"
    except Exception:
        logger.exception("Aviso de vencimiento por OTP falló")
        return "retry"


async def _ensure_expiry_in_app_notice(
    seller: dict[str, Any],
    *,
    ends_at: Any,
    days_remaining: int,
    existing: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if existing is not None:
        return existing

    now = to_utc_naive(utc_now())
    is_trial = bool(seller.get("is_trial"))
    document = {
        "_id": ObjectId(),
        "seller_id": seller["_id"],
        "batch_id": f"subscription-expiring-{seller['_id']}-{ends_at.isoformat()}",
        "kind": NOTIFICATION_KIND_EXPIRING,
        "subscription_ends_at": ends_at,
        "title": expiry_notice_title(is_trial=is_trial),
        "content": warning_notification_content(days_remaining, is_trial=is_trial),
        "action_label": "Renovar plan",
        "action_type": ACTION_RENEW_SUBSCRIPTION,
        "read_at": None,
        "created_at": now,
        "created_by_admin_id": None,
    }
    await get_notifications_collection().insert_one(document)
    await publish_seller_notification(str(seller["_id"]), _document_to_public(document))
    return document


async def _send_subscription_contact_reminder(
    seller: dict[str, Any],
    *,
    days_remaining: int,
    ends_at: Any,
) -> None:
    message = contact_reminder_content(
        days_remaining,
        store_name=seller.get("store_name"),
        is_trial=bool(seller.get("is_trial")),
    )
    sms_state = expiry_notice_channel_state(seller, "sms", ends_at)
    updates: dict[str, Any] = {EXPIRY_NOTICE_FOR_FIELD: to_utc_naive(ends_at)}

    if sms_state not in ("sent", "skipped"):
        phone = _seller_phone_e164(seller)
        if not phone:
            sms_state = "skipped"
        else:
            status_value = await _deliver_contact_channel(
                lambda: send_custom_sms(phone_e164=phone, message=message)
            )
            sms_state = "sent" if status_value == "sent" else status_value
        updates["subscription_expiry_notice_sms"] = sms_state
        updates[EXPIRY_NOTICE_SMS_FIELD] = sms_state == "sent"

    if len(updates) == 1:
        return

    await get_registrations_collection().update_one({"_id": seller["_id"]}, {"$set": updates})
    seller.update(updates)


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
        from_admin=_is_admin_notification(doc),
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
        {
            "_id": 1,
            "subscription_ends_at": 1,
            "phone": 1,
            "store_name": 1,
            "is_trial": 1,
            EXPIRY_NOTICE_FOR_FIELD: 1,
            EXPIRY_NOTICE_SMS_FIELD: 1,
            "subscription_expiry_notice_sms": 1,
        },
    )

    async for doc in cursor:
        in_warning = is_within_warning_window(doc, now=now)
        in_contact = is_within_contact_reminder_window(doc, now=now)
        if not in_warning and not in_contact:
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
        if existing is None and (in_warning or in_contact):
            existing = await _ensure_expiry_in_app_notice(
                doc,
                ends_at=ends_at,
                days_remaining=days_remaining,
                existing=None,
            )
            created += 1

        if in_contact:
            await _send_subscription_contact_reminder(
                doc,
                days_remaining=days_remaining,
                ends_at=ends_at,
            )

    return created


async def _subscription_reminder_loop() -> None:
    while True:
        await asyncio.sleep(SUBSCRIPTION_REMINDER_POLL_SECONDS)
        try:
            await ensure_subscription_expiring_notifications()
        except Exception:
            logger.exception("Error al revisar suscripciones por vencer")


def start_subscription_reminder_task() -> asyncio.Task:
    global _reminder_task
    if _reminder_task is None or _reminder_task.done():
        _reminder_task = asyncio.create_task(_subscription_reminder_loop())
    return _reminder_task


async def stop_subscription_reminder_task() -> None:
    global _reminder_task
    if _reminder_task is None:
        return
    _reminder_task.cancel()
    try:
        await _reminder_task
    except asyncio.CancelledError:
        pass
    _reminder_task = None


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
    document = {
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
    }
    await collection.insert_one(document)
    await publish_seller_notification(str(seller_object_id), _document_to_public(document))


AUDIENCE_SPECS: dict[str, tuple[str, str]] = {
    "premium_monthly": (PREMIUM_PLAN_TIER, "monthly"),
    "premium_quarterly": (PREMIUM_PLAN_TIER, "quarterly"),
    "premium_yearly": (PREMIUM_PLAN_TIER, "yearly"),
    "pro_monthly": (PRO_PLAN_TIER, "monthly"),
    "pro_quarterly": (PRO_PLAN_TIER, "quarterly"),
    "pro_yearly": (PRO_PLAN_TIER, "yearly"),
    "standard_monthly": (STANDARD_PLAN_TIER, "monthly"),
    "standard_quarterly": (STANDARD_PLAN_TIER, "quarterly"),
    "standard_yearly": (STANDARD_PLAN_TIER, "yearly"),
}

AUDIENCE_EMPTY_MESSAGES: dict[str, str] = {
    "premium_monthly": "No hay vendedores Premium con facturación mensual activos.",
    "premium_quarterly": "No hay vendedores Premium con facturación trimestral activos.",
    "premium_yearly": "No hay vendedores Premium con facturación anual activos.",
    "pro_monthly": "No hay vendedores Pro con facturación mensual activos.",
    "pro_quarterly": "No hay vendedores Pro con facturación trimestral activos.",
    "pro_yearly": "No hay vendedores Pro con facturación anual activos.",
    "standard_monthly": "No hay vendedores Básico con facturación mensual activos.",
    "standard_quarterly": "No hay vendedores Básico con facturación trimestral activos.",
    "standard_yearly": "No hay vendedores Básico con facturación anual activos.",
}


def _seller_matches_audience(seller: dict[str, Any], audience: str) -> bool:
    if audience == "all":
        return True
    spec = AUDIENCE_SPECS.get(audience)
    if spec is None:
        return False
    tier, billing = spec
    return (
        normalize_plan_tier(seller.get("plan_tier")) == tier
        and normalize_billing_period(seller.get("billing_period")) == billing
    )


def _filter_sellers_by_audience(
    sellers: list[dict[str, Any]],
    audience: NotificationAudienceInput,
) -> list[dict[str, Any]]:
    return _filter_sellers_by_audiences(sellers, [audience])


def _filter_sellers_by_audiences(
    sellers: list[dict[str, Any]],
    audiences: list[str],
) -> list[dict[str, Any]]:
    groups = [item for item in audiences if item and item != "single"]
    if "all" in groups:
        return sellers
    if not groups:
        return []
    return [
        seller
        for seller in sellers
        if any(_seller_matches_audience(seller, audience) for audience in groups)
    ]


def _stored_audience(groups: list[str], seller_ids: list[str]) -> str:
    if "all" in groups:
        return "all"
    if len(groups) == 1:
        return groups[0]
    if len(groups) > 1:
        return "mixed"
    if seller_ids:
        return "single"
    return "all"


def _audience_empty_message(audience: NotificationAudienceInput) -> str:
    return AUDIENCE_EMPTY_MESSAGES.get(
        audience,
        "No hay vendedores activos para recibir la notificación.",
    )


async def _resolve_single_seller(seller_id: str) -> dict[str, Any]:
    try:
        seller_oid = ObjectId(seller_id.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identificador de negocio no válido.",
        ) from exc

    seller = await get_registrations_collection().find_one(
        {
            "_id": seller_oid,
            "status": {"$in": ["approved", "expired"]},
        },
        {
            "_id": 1,
            "store_name": 1,
            "status": 1,
            "subscription_ends_at": 1,
            "plan_tier": 1,
            "billing_period": 1,
            "phone": 1,
        },
    )
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Negocio no encontrado o no disponible para notificar.",
        )
    return seller


_SELLER_NOTIFY_PROJECTION = {
    "_id": 1,
    "subscription_ends_at": 1,
    "status": 1,
    "plan_tier": 1,
    "billing_period": 1,
    "store_name": 1,
    "phone": 1,
}


async def _load_active_sellers() -> list[dict[str, Any]]:
    sellers = await get_registrations_collection().find(
        {"status": "approved"},
        _SELLER_NOTIFY_PROJECTION,
    ).to_list(length=None)
    return [seller for seller in sellers if is_subscription_active(seller)]


async def _resolve_notification_sellers(
    *,
    groups: list[str],
    seller_ids: list[str],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if groups:
        active = await _load_active_sellers()
        for seller in _filter_sellers_by_audiences(active, groups):
            by_id[str(seller["_id"])] = seller
    for seller_id in seller_ids:
        key = str(seller_id).strip()
        if not key or key in by_id:
            continue
        by_id[key] = await _resolve_single_seller(key)
    return list(by_id.values())


async def send_notification_to_sellers(
    admin_id: str,
    title: str,
    content: str,
    audience: NotificationAudienceInput = "all",
    *,
    seller_id: str | None = None,
    audiences: list[str] | None = None,
    seller_ids: list[str] | None = None,
) -> AdminNotificationSendResult:
    groups = [item for item in (audiences or []) if item and item != "single"]
    if not groups and audience and audience != "single":
        groups = [audience]
    if "all" in groups:
        groups = ["all"]

    ids: list[str] = []
    seen_ids: set[str] = set()
    for raw in [*(seller_ids or []), seller_id or ""]:
        key = str(raw or "").strip()
        if not key or key in seen_ids:
            continue
        seen_ids.add(key)
        ids.append(key)

    if not groups and not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Elige al menos un grupo o un negocio.",
        )

    sellers = await _resolve_notification_sellers(groups=groups, seller_ids=ids)
    audience = _stored_audience(groups, ids)
    stored_audiences = groups if groups else ["single"]
    target_store_name: str | None = None
    if audience == "single" and len(sellers) == 1:
        target_store_name = (sellers[0].get("store_name") or "Tienda").strip() or "Tienda"

    if not sellers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_audience_empty_message(groups[0] if len(groups) == 1 else "mixed"),
        )

    try:
        admin_object_id = ObjectId(admin_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin no válido.",
        ) from exc

    now = to_utc_naive(utc_now())
    batch_id = uuid.uuid4().hex
    title_clean = title.strip()
    content_clean = content.strip()

    documents = [
        {
            "_id": ObjectId(),
            "seller_id": seller["_id"],
            "batch_id": batch_id,
            "title": title_clean,
            "content": content_clean,
            "audience": audience,
            "audiences": stored_audiences,
            "target_store_name": target_store_name,
            "sms_send_count": 0,
            "read_at": None,
            "created_at": now,
            "created_by_admin_id": admin_object_id,
        }
        for seller in sellers
    ]

    collection = get_notifications_collection()
    await collection.insert_many(documents)
    for document in documents:
        await publish_seller_notification(str(document["seller_id"]), _document_to_public(document))

    events: list[AdminNotificationSendEvent] = [
        AdminNotificationSendEvent(
            type="success",
            message=(
                f"Aviso enviado a {target_store_name}."
                if audience == "single" and len(documents) == 1 and target_store_name
                else f"Aviso enviado a {len(documents)} vendedor{'es' if len(documents) != 1 else ''}."
            ),
        )
    ]

    return AdminNotificationSendResult(
        batch_id=batch_id,
        title=title_clean,
        content=content_clean,
        audience=audience,
        audiences=stored_audiences,
        recipient_count=len(documents),
        created_at=now,
        target_store_name=target_store_name,
        sms_sent=False,
        sms_send_count=0,
        events=events,
    )


def _sms_targets_from_sellers(sellers: list[dict[str, Any]]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    seen_phones: set[str] = set()
    for seller in sellers:
        phone = _seller_phone_e164(seller)
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)
        store_name = (seller.get("store_name") or "Tienda").strip() or "Tienda"
        targets.append((phone, store_name))
    return targets


async def _send_aviso_sms(
    *,
    title: str,
    content: str,
    sms_targets: list[tuple[str, str]],
) -> tuple[bool, str | None, list[AdminNotificationSendEvent]]:
    events: list[AdminNotificationSendEvent] = []
    if not sms_targets:
        sms_error = "No hay teléfonos para enviar el SMS del aviso."
        events.append(AdminNotificationSendEvent(type="error", message=sms_error))
        return False, sms_error, events

    sms_body = title if not content else f"{title}\n{content}"
    phones = [phone for phone, _store in sms_targets]
    sms_sent = False
    sms_error: str | None = None
    campaign_failed = False
    try:
        await send_sms_campaign(
            name=title,
            message=sms_body,
            recipients=phones,
        )
        sms_sent = True
        events.append(
            AdminNotificationSendEvent(
                type="success",
                message=f"SMS de campaña enviado a {len(phones)} número{'s' if len(phones) != 1 else ''}.",
            )
        )
        return sms_sent, None, events
    except HTTPException as exc:
        campaign_failed = True
        sms_error = _sms_error_message(exc.detail)
        events.append(
            AdminNotificationSendEvent(
                type="error",
                message=f"La campaña SMS falló: {sms_error}",
            )
        )
    except Exception:
        campaign_failed = True
        sms_error = "No pudimos enviar el SMS del aviso."
        events.append(AdminNotificationSendEvent(type="error", message=sms_error))

    if not campaign_failed:
        return sms_sent, sms_error, events

    sent_count = 0
    fail_count = 0
    last_fail: str | None = None
    for index, (phone, store_name) in enumerate(sms_targets):
        if index:
            await asyncio.sleep(0.7)
        try:
            await send_custom_sms(phone_e164=phone, message=sms_body)
            sent_count += 1
            sms_sent = True
            events.append(
                AdminNotificationSendEvent(
                    type="success",
                    message=f"SMS enviado a {store_name} ({phone}).",
                )
            )
        except HTTPException as exc:
            fail_count += 1
            last_fail = _sms_error_message(exc.detail)
            events.append(
                AdminNotificationSendEvent(
                    type="error",
                    message=f"SMS a {store_name} ({phone}): {last_fail}",
                )
            )
        except Exception:
            fail_count += 1
            last_fail = "No pudimos enviar el SMS del aviso."
            events.append(
                AdminNotificationSendEvent(
                    type="error",
                    message=f"SMS a {store_name} ({phone}): {last_fail}",
                )
            )
    if fail_count and not sent_count:
        sms_error = last_fail or sms_error
    elif fail_count:
        sms_error = f"SMS individuales: {sent_count} enviados, {fail_count} fallidos."
    elif sent_count:
        sms_error = None
    return sms_sent, sms_error, events


async def send_broadcast_sms(batch_id: str) -> AdminNotificationSendResult:
    key = (batch_id or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aviso no válido.",
        )

    collection = get_notifications_collection()
    documents = await collection.find(
        {
            "batch_id": key,
            "created_by_admin_id": {"$type": "objectId"},
        }
    ).to_list(length=None)
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aviso no encontrado.",
        )

    first = documents[0]
    title_clean = str(first.get("title") or "").strip()
    content_clean = str(first.get("content") or "").strip()
    audience = first.get("audience") or "all"
    stored_audiences = list(first.get("audiences") or [])
    target_store_name = first.get("target_store_name")
    created_at = first.get("created_at") or to_utc_naive(utc_now())
    sms_send_count = int(first.get("sms_send_count") or 0)

    seller_oids: list[ObjectId] = []
    seen: set[str] = set()
    for document in documents:
        seller_id = document.get("seller_id")
        key_id = str(seller_id or "")
        if not key_id or key_id in seen:
            continue
        seen.add(key_id)
        if isinstance(seller_id, ObjectId):
            seller_oids.append(seller_id)
        else:
            try:
                seller_oids.append(ObjectId(key_id))
            except Exception:
                continue

    sellers = []
    if seller_oids:
        sellers = await get_registrations_collection().find(
            {"_id": {"$in": seller_oids}},
            {"_id": 1, "store_name": 1, "phone": 1},
        ).to_list(length=None)

    sms_sent, sms_error, events = await _send_aviso_sms(
        title=title_clean,
        content=content_clean,
        sms_targets=_sms_targets_from_sellers(sellers),
    )
    if sms_sent:
        sms_send_count += 1
        await collection.update_many(
            {"batch_id": key, "created_by_admin_id": {"$type": "objectId"}},
            {"$set": {"sms_send_count": sms_send_count}},
        )

    return AdminNotificationSendResult(
        batch_id=key,
        title=title_clean,
        content=content_clean,
        audience=audience,
        audiences=stored_audiences,
        recipient_count=len(documents),
        created_at=created_at,
        target_store_name=target_store_name,
        sms_sent=sms_sent,
        sms_error=sms_error,
        sms_send_count=sms_send_count,
        events=events,
    )


async def list_admin_broadcasts(limit: int = 30) -> list[AdminNotificationBroadcastPublic]:
    collection = get_notifications_collection()
    pipeline = [
        # Solo avisos emitidos por un admin; excluye pedidos, suscripciones, etc.
        {"$match": {"created_by_admin_id": {"$type": "objectId"}}},
        {"$sort": {"created_at": DESCENDING}},
        {
            "$group": {
                "_id": "$batch_id",
                "title": {"$first": "$title"},
                "content": {"$first": "$content"},
                "audience": {"$first": "$audience"},
                "audiences": {"$first": "$audiences"},
                "target_store_name": {"$first": "$target_store_name"},
                "created_at": {"$first": "$created_at"},
                "sms_send_count": {"$max": "$sms_send_count"},
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
            audience=row.get("audience") or "all",
            audiences=list(row.get("audiences") or []),
            recipient_count=row["recipient_count"],
            created_at=row["created_at"],
            target_store_name=row.get("target_store_name"),
            sms_send_count=int(row.get("sms_send_count") or 0),
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


async def mark_system_notifications_read(
    seller_id: str,
) -> SellerNotificationBulkReadResult:
    try:
        seller_object_id = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        ) from exc

    now = to_utc_naive(utc_now())
    collection = get_notifications_collection()
    result = await collection.update_many(
        _system_notifications_filter(seller_object_id),
        {"$set": {"read_at": now}},
    )
    return SellerNotificationBulkReadResult(marked_count=result.modified_count)
