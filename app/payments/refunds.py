"""Reembolso QvaPay a partir de lo que se quita del pedido."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.database import get_disputes_collection, get_orders_collection, get_registrations_collection
from app.payments.qvapay import transfer_to_user
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _as_float(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def clean_refund_images(images: list[str]) -> list[str]:
    clean = []
    for raw in images:
        src = str(raw or "").strip()
        if not src or ".." in src.split("/"):
            raise HTTPException(status_code=400, detail="La imagen del motivo no es válida.")
        parsed = urlparse(src)
        allowed = src.startswith("/uploads/refund-reasons/") or parsed.hostname == "res.cloudinary.com"
        if not allowed:
            raise HTTPException(status_code=400, detail="La imagen del motivo no es válida.")
        clean.append(src)
    if not clean or len(clean) > 6:
        raise HTTPException(status_code=400, detail="Adjunta entre 1 y 6 imágenes del motivo.")
    return clean


def plan_adjustment(
    order: dict[str, Any],
    quantities: dict[str, int] | None,
    refund_delivery: bool,
) -> dict[str, Any]:
    """Calcula la devolución con la comisión ya cobrada, sin usar el porcentaje nuevo."""
    qvapay = order.get("qvapay") if isinstance(order.get("qvapay"), dict) else {}
    items = [item for item in order.get("items") or [] if isinstance(item, dict)]
    current = {str(item.get("product_id") or ""): item for item in items}
    if "" in current:
        raise HTTPException(status_code=400, detail="El pedido tiene un producto sin identificador.")

    full_refund = quantities is None
    requested = {str(key): int(value) for key, value in (quantities or {}).items()}
    if not full_refund and set(requested) != set(current):
        raise HTTPException(status_code=400, detail="Indica la cantidad de cada producto del pedido.")

    original_value = Decimal("0")
    removed_value = Decimal("0")
    next_items: list[dict[str, Any]] = []
    for product_id, item in current.items():
        old_qty = int(item.get("quantity") or 0)
        new_qty = 0 if full_refund else int(requested[product_id])
        if new_qty < 0 or new_qty > old_qty:
            raise HTTPException(status_code=400, detail="Solo puedes bajar cantidades o quitar productos.")
        line = Decimal(str(item.get("line_total") if item.get("line_total") is not None else float(item.get("unit_price") or 0) * old_qty))
        original_value += line
        if old_qty:
            removed_value += line * Decimal(old_qty - new_qty) / Decimal(old_qty)
        if new_qty > 0:
            kept = dict(item)
            kept["quantity"] = new_qty
            kept_line = (line * Decimal(new_qty) / Decimal(old_qty)).quantize(CENT, rounding=ROUND_HALF_UP) if old_qty else Decimal("0")
            kept["line_total"] = _as_float(kept_line)
            next_items.append(kept)

    products_usd = _money(qvapay.get("products_amount_usd"))
    delivery_usd = _money(qvapay.get("delivery_amount_usd"))
    fee_usd = _money(qvapay.get("fee_usd"))
    invoice_usd = _money(qvapay.get("invoice_amount_usd"))
    if invoice_usd <= 0:
        invoice_usd = (products_usd + delivery_usd + fee_usd).quantize(CENT, rounding=ROUND_HALF_UP)
    if delivery_usd <= 0:
        refund_delivery = False
    if full_refund:
        refund_delivery = delivery_usd > 0

    removed_products = (
        (products_usd * removed_value / original_value).quantize(CENT, rounding=ROUND_HALF_UP)
        if original_value > 0 else Decimal("0")
    )
    if removed_products > products_usd:
        removed_products = products_usd
    removed_delivery = delivery_usd if refund_delivery else Decimal("0")
    portion = (removed_products + removed_delivery).quantize(CENT, rounding=ROUND_HALF_UP)
    base = (products_usd + delivery_usd).quantize(CENT, rounding=ROUND_HALF_UP)
    fee_part = (fee_usd * portion / base).quantize(CENT, rounding=ROUND_HALF_UP) if base > 0 else Decimal("0")
    if fee_part > fee_usd:
        fee_part = fee_usd

    remaining_products = (products_usd - removed_products).quantize(CENT, rounding=ROUND_HALF_UP)
    remaining_delivery = Decimal("0") if refund_delivery else delivery_usd
    remaining_fee = (fee_usd - fee_part).quantize(CENT, rounding=ROUND_HALF_UP)
    nothing_left = not next_items and remaining_delivery <= 0
    if nothing_left:
        buyer = invoice_usd
        remaining_products = Decimal("0")
        remaining_delivery = Decimal("0")
        remaining_fee = Decimal("0")
        next_items = []
    else:
        buyer = (portion + fee_part).quantize(CENT, rounding=ROUND_HALF_UP)
        if buyer > invoice_usd:
            buyer = invoice_usd
    if not full_refund and portion <= 0:
        raise HTTPException(status_code=400, detail="Indica qué vas a devolver.")
    if buyer <= 0:
        raise HTTPException(status_code=400, detail="No hay un monto para devolver.")

    remaining_invoice = invoice_usd if nothing_left else (remaining_products + remaining_delivery + remaining_fee).quantize(CENT, rounding=ROUND_HALF_UP)
    if nothing_left:
        remaining_invoice = Decimal("0")
    store_payout = (remaining_products + remaining_delivery).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "buyer_amount_usd": _as_float(buyer),
        "store_payout_usd": _as_float(store_payout),
        "products_amount_usd": _as_float(remaining_products),
        "delivery_amount_usd": _as_float(remaining_delivery),
        "fee_usd": _as_float(remaining_fee),
        "invoice_amount_usd": _as_float(remaining_invoice),
        "items": next_items,
        "refund_delivery": refund_delivery or full_refund and delivery_usd > 0,
        "nothing_left": nothing_left,
    }


def _refundable(order: dict[str, Any]) -> dict[str, Any]:
    if order.get("status") in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="El pedido ya está cerrado.")
    qvapay = order.get("qvapay") if isinstance(order.get("qvapay"), dict) else None
    if order.get("payment_method") != "qvapay" or not qvapay:
        raise HTTPException(status_code=400, detail="El pedido no usa pago QvaPay.")
    if qvapay.get("payment_status") != "paid":
        raise HTTPException(status_code=409, detail="El pago todavía no entró.")
    if qvapay.get("release_status") not in {"held", "retry"}:
        raise HTTPException(status_code=409, detail="El pago ya no está retenido.")
    if float(qvapay.get("pending_store_payout_usd") or 0) > 0:
        raise HTTPException(status_code=409, detail="Hay un pago a la tienda pendiente de reintento.")
    if qvapay.get("buyer_support_reported") or qvapay.get("seller_support_reported"):
        raise HTTPException(status_code=409, detail="Hay una disputa abierta. La ajusta el administrador.")
    return qvapay


async def _assert_no_open_dispute(order_id: ObjectId) -> None:
    dispute = await get_disputes_collection().find_one({"order_id": order_id, "status": "open"}, {"_id": 1})
    if dispute:
        raise HTTPException(status_code=409, detail="Hay una disputa abierta. La ajusta el administrador.")


async def upload_refund_image(seller_id: str, order_id: str, file) -> dict[str, str]:
    from app.catalogs.media_storage import read_image_upload, store_image
    from app.payments.service import _seller_order

    order = await _seller_order(seller_id, order_id)
    _refundable(order)
    await _assert_no_open_dispute(order["_id"])
    content, content_type = await read_image_upload(file)
    stored = await store_image(content, content_type, scope="refund-reasons", owner_id=seller_id)
    return {"url": stored.url}


def _subtotals(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.orders.service import _calc_subtotals

    return [entry.model_dump() for entry in _calc_subtotals(items)]


async def _buyer_username(order: dict[str, Any], qvapay: dict[str, Any]) -> str:
    username = str(qvapay.get("buyer_username") or "").strip()
    if username:
        return username
    from app.payments.disputes import _buyer_qvapay_username

    return await _buyer_qvapay_username(order)


async def refund_order_for_store(
    seller_id: str,
    order_id: str,
    *,
    quantities: dict[str, int],
    refund_delivery: bool,
    text: str,
    images: list[str],
) -> dict[str, Any]:
    from app.payments.service import _notify_customer, _seller_order

    order = await _seller_order(seller_id, order_id)
    qvapay = _refundable(order)
    await _assert_no_open_dispute(order["_id"])
    images = clean_refund_images(images)
    reason = " ".join(str(text or "").split())
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="Escribe el motivo del reembolso.")
    plan = plan_adjustment(order, quantities, refund_delivery)
    username = await _buyer_username(order, qvapay)
    if not username:
        raise HTTPException(status_code=409, detail="El comprador no tiene un usuario QvaPay.")

    sequence = int(qvapay.get("refund_count") or 0) + 1
    now = to_utc_naive(utc_now())
    claim = await get_orders_collection().update_one(
        {
            "_id": order["_id"],
            "qvapay.payment_status": "paid",
            "qvapay.release_status": {"$in": ["held", "retry"]},
        },
        {"$set": {"qvapay.release_status": "transferring", "updated_at": now}},
    )
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="El pago ya no está retenido.")

    idempotency = f"store-order-{order['_id']}-refund-{sequence}"
    try:
        transaction = await transfer_to_user(
            amount=plan["buyer_amount_usd"],
            username=username,
            description=f"Devolución pedido {str(order['_id'])[-6:].upper()}",
            idempotency_key=idempotency,
        )
    except Exception:
        logger.exception("No se pudo reembolsar el pedido %s", order_id)
        await get_orders_collection().update_one(
            {"_id": order["_id"], "qvapay.release_status": "transferring"},
            {"$set": {"qvapay.release_status": "held", "updated_at": to_utc_naive(utc_now())}},
        )
        raise HTTPException(status_code=503, detail="No pudimos devolver el pago. El pedido sigue retenido.")

    finished = to_utc_naive(utc_now())
    updates: dict[str, Any] = {
        "items": plan["items"],
        "subtotals": _subtotals(plan["items"]),
        "qvapay.products_amount_usd": plan["products_amount_usd"],
        "qvapay.delivery_amount_usd": plan["delivery_amount_usd"],
        "qvapay.fee_usd": plan["fee_usd"],
        "qvapay.invoice_amount_usd": plan["invoice_amount_usd"],
        "qvapay.refund_count": sequence,
        "qvapay.refund_amount_usd": plan["buyer_amount_usd"],
        "qvapay.refund_transfer_id": transaction,
        "qvapay.buyer_username": username,
        "updated_at": finished,
    }
    if plan["refund_delivery"]:
        updates["delivery_price"] = 0
    if plan["nothing_left"]:
        updates.update({
            "status": "cancelled",
            "cancelled_at": finished,
            "qvapay.release_status": "refunded",
            "qvapay.payment_status": "refunded",
            "qvapay.invoice_amount_usd": 0,
        })
        if isinstance(qvapay.get("evidence"), dict):
            updates["qvapay.evidence.status"] = "closed"
    else:
        updates["qvapay.release_status"] = "held"

    saved = await get_orders_collection().find_one_and_update(
        {"_id": order["_id"], "qvapay.release_status": "transferring"},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    amount_label = f"{plan['buyer_amount_usd']:.2f}"
    await _notify_customer(
        order.get("buyer_id"),
        str(order["_id"]),
        f"Reembolso de {amount_label} USD",
        reason,
        "qvapay_refund",
        images=images,
        sms=False,
    )
    from app.live.hub import publish_seller_data_update
    await publish_seller_data_update(str(seller_id), "orders")
    return {
        "order_id": str(order["_id"]),
        "refund_amount_usd": plan["buyer_amount_usd"],
        "release_status": (saved or {}).get("qvapay", {}).get("release_status") if isinstance((saved or {}).get("qvapay"), dict) else updates.get("qvapay.release_status"),
        "status": (saved or {}).get("status") or updates.get("status") or order.get("status"),
    }


async def store_payout_username(order: dict[str, Any]) -> str:
    qvapay = order.get("qvapay") if isinstance(order.get("qvapay"), dict) else {}
    username = str(qvapay.get("payout_username") or "").strip()
    if username:
        return username
    try:
        seller = await get_registrations_collection().find_one(
            {"_id": ObjectId(str(order.get("seller_id") or ""))},
            {"qvapay_username": 1},
        )
    except Exception:
        return ""
    return str((seller or {}).get("qvapay_username") or "").strip()
