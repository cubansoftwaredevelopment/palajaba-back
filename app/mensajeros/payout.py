"""Reparte el pago QvaPay entre la tienda y el mensajero, si la tienda lo eligió."""

from __future__ import annotations

import logging

from bson import ObjectId

from app.database import (
    get_mensajeria_asignaciones_collection,
    get_mensajeros_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.payments.qvapay import transfer_to_user
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)


async def courier_qvapay_share(order: dict) -> tuple[float, str, bool]:
    """Devuelve (usd, usuario, ya_transferido). Sin usuario o sin elección QvaPay, usd es 0."""
    assignment = await get_mensajeria_asignaciones_collection().find_one(
        {"order_id": order["_id"], "pay_via": "qvapay", "status": {"$ne": "cancelled"}},
        sort=[("created_at", -1)],
    )
    if not assignment:
        return 0.0, "", False
    usd = round(float(assignment.get("fee_amount_usd") or 0), 2)
    if usd <= 0:
        return 0.0, "", bool(assignment.get("qvapay_transfer_id"))
    messenger = await get_mensajeros_collection().find_one({"_id": assignment["mensajero_id"]})
    username = str((messenger or {}).get("qvapay_username") or "").strip()
    verified = bool((messenger or {}).get("qvapay_verified_at"))
    if not username or not verified:
        return 0.0, "", False
    return usd, username, bool(assignment.get("qvapay_transfer_id"))


async def pay_courier_share(order: dict) -> None:
    usd, username, transferred = await courier_qvapay_share(order)
    if usd <= 0 or not username or transferred:
        return
    try:
        transaction = await transfer_to_user(
            amount=usd,
            username=username,
            description=f"Mensajería pedido {str(order['_id'])[-6:].upper()}",
            idempotency_key=f"courier-order-{order['_id']}-release",
        )
    except Exception:
        logger.exception("No se pudo transferir la parte del mensajero %s", order["_id"])
        raise
    now = to_utc_naive(utc_now())
    await get_mensajeria_asignaciones_collection().update_one(
        {"order_id": order["_id"], "pay_via": "qvapay", "status": {"$ne": "cancelled"}, "qvapay_transfer_id": {"$exists": False}},
        {"$set": {"qvapay_transfer_id": transaction, "qvapay_paid_at": now, "updated_at": now}},
    )


async def store_release_amount(order: dict) -> tuple[float, str]:
    qvapay = order.get("qvapay") or {}
    total = round(float(qvapay.get("products_amount_usd") or 0) + float(qvapay.get("delivery_amount_usd") or 0), 2)
    usd, username, _transferred = await courier_qvapay_share(order)
    cut = usd if username else 0.0
    store_amount = round(max(0.0, total - cut), 2)
    payout_username = str(qvapay.get("payout_username") or "").strip()
    if not payout_username:
        seller = await get_registrations_collection().find_one({"_id": _seller_oid(order)})
        payout_username = str((seller or {}).get("qvapay_username") or "").strip()
    return store_amount, payout_username


def _seller_oid(order: dict) -> ObjectId:
    raw = order.get("seller_id")
    if isinstance(raw, ObjectId):
        return raw
    return ObjectId(str(raw))


async def refresh_order(order_id: ObjectId) -> dict | None:
    return await get_orders_collection().find_one({"_id": order_id})
