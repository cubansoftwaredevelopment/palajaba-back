from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import HTTPException, UploadFile, status
from pymongo import ReturnDocument

from app.auth.registrations import phone_e164
from app.config import settings
from app.database import (
    get_customer_notifications_collection,
    get_customers_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.live.hub import publish_seller_notification
from app.notifications.otp_manager import send_custom_sms
from app.notifications.schemas import SellerNotificationPublic
from app.payments.qvapay import create_invoice, qvapay_escrow_configured, transfer_to_user, verify_qvapay_username
from app.services.exchange_rates import get_cup_per_unit
from app.catalogs.media_storage import read_image_upload, store_image
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)
EVIDENCE_WINDOW = timedelta(hours=48)
EVIDENCE_WARNING = (
    "Acepta solo si recibiste tu pedido. Si aún no lo recibiste, rechaza la evidencia ahora "
    "y contacta a soporte. No esperes a que venza el plazo de 48 horas: el pago se liberará automáticamente."
)
_expiry_task: asyncio.Task | None = None


def _oid(value: str, message: str) -> ObjectId:
    try:
        return ObjectId(str(value).strip())
    except Exception as exc:
        raise HTTPException(status_code=404, detail=message) from exc


async def get_qvapay_account(seller_id: str) -> dict[str, Any]:
    seller = await get_registrations_collection().find_one(
        {"_id": _oid(seller_id, "Tienda no encontrada.")},
        {"qvapay_username": 1, "qvapay_verified_at": 1, "qvapay_prompt_dismissed": 1},
    )
    if seller is None:
        raise HTTPException(status_code=404, detail="Tienda no encontrada.")
    return {
        "username": seller.get("qvapay_username"),
        "verified": bool(seller.get("qvapay_username") and seller.get("qvapay_verified_at")),
        "prompt_dismissed": bool(seller.get("qvapay_prompt_dismissed")),
    }


async def save_qvapay_account(
    seller_id: str,
    username: str,
    *,
    skip_verification_on_service_error: bool = False,
) -> dict[str, Any]:
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Escribe tu usuario QvaPay.")
    verified = True
    try:
        normalized = await verify_qvapay_username(normalized)
    except HTTPException as exc:
        if not skip_verification_on_service_error or exc.status_code != 503:
            raise
        verified = False

    collection = get_registrations_collection()
    update = {"$set": {"qvapay_username": normalized}}
    if verified:
        update["$set"]["qvapay_verified_at"] = to_utc_naive(utc_now())
    else:
        update["$unset"] = {"qvapay_verified_at": ""}
    result = await collection.update_one(
        {"_id": _oid(seller_id, "Tienda no encontrada.")},
        update,
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Tienda no encontrada.")
    return {"username": normalized, "verified": verified}


async def get_customer_qvapay_account(customer_id: str) -> dict[str, Any]:
    customer = await get_customers_collection().find_one(
        {"_id": _oid(customer_id, "Cliente no encontrado.")},
        {"qvapay_username": 1, "qvapay_verified_at": 1, "qvapay_prompt_dismissed": 1},
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return {
        "username": customer.get("qvapay_username"),
        "verified": bool(customer.get("qvapay_username") and customer.get("qvapay_verified_at")),
        "prompt_dismissed": bool(customer.get("qvapay_prompt_dismissed")),
    }


async def save_customer_qvapay_account(
    customer_id: str,
    username: str,
    *,
    skip_verification_on_service_error: bool = False,
) -> dict[str, Any]:
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Escribe tu usuario QvaPay.")
    verified = True
    try:
        normalized = await verify_qvapay_username(normalized)
    except HTTPException as exc:
        if not skip_verification_on_service_error or exc.status_code != 503:
            raise
        verified = False
    update: dict[str, Any] = {"$set": {"qvapay_username": normalized}}
    if verified:
        update["$set"]["qvapay_verified_at"] = to_utc_naive(utc_now())
    else:
        update["$unset"] = {"qvapay_verified_at": ""}
    result = await get_customers_collection().update_one({"_id": _oid(customer_id, "Cliente no encontrado.")}, update)
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return {"username": normalized, "verified": verified, "prompt_dismissed": False}


async def delete_customer_qvapay_account(customer_id: str) -> None:
    result = await get_customers_collection().update_one(
        {"_id": _oid(customer_id, "Cliente no encontrado.")},
        {"$unset": {"qvapay_username": "", "qvapay_verified_at": ""}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")


async def dismiss_customer_qvapay_prompt(customer_id: str) -> None:
    result = await get_customers_collection().update_one(
        {"_id": _oid(customer_id, "Cliente no encontrado.")},
        {"$set": {"qvapay_prompt_dismissed": True}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")


async def dismiss_qvapay_prompt(seller_id: str) -> None:
    result = await get_registrations_collection().update_one(
        {"_id": _oid(seller_id, "Tienda no encontrada.")},
        {"$set": {"qvapay_prompt_dismissed": True}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Tienda no encontrada.")


async def delete_qvapay_account(seller_id: str) -> None:
    result = await get_registrations_collection().update_one(
        {"_id": _oid(seller_id, "Tienda no encontrada.")},
        {"$unset": {"qvapay_username": "", "qvapay_verified_at": ""}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Tienda no encontrada.")


def _usd(amount: float, currency: str, rates: dict[str, float]) -> float:
    # QUSD es la moneda de QvaPay y vale 1 a 1 con el USD.
    if currency in {"USD", "QUSD"}:
        return round(float(amount), 2)
    from_rate, usd_rate = rates.get(currency), rates.get("USD")
    if not from_rate or not usd_rate:
        raise HTTPException(status_code=503, detail=f"No hay tasa disponible para {currency}.")
    return round(float(amount) * float(from_rate) / float(usd_rate), 2)


def payment_quote(
    order: dict[str, Any],
    delivery_price: float | None,
    delivery_currency: str | None,
    *,
    fee_percent: float = 0,
) -> dict[str, Any]:
    rates = get_cup_per_unit()
    products_usd = round(sum(
        _usd(float(item.get("line_total") or float(item["unit_price"]) * int(item["quantity"])), item["currency"], rates)
        for item in order.get("items") or []
    ), 2)
    if order.get("delivery_requested") and delivery_price is None:
        raise HTTPException(status_code=400, detail="Indica el costo del domicilio antes de crear la factura.")
    delivery_usd = _usd(float(delivery_price), delivery_currency or "CUP", rates) if delivery_price is not None else 0.0
    base = Decimal(str(products_usd + delivery_usd))
    percent = Decimal(str(fee_percent or 0))
    if percent < 0:
        percent = Decimal("0")
    fee_decimal = (base * percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fee = float(fee_decimal)
    total = round(products_usd + delivery_usd + fee, 2)
    return {
        "products_amount_usd": products_usd,
        "delivery_amount_usd": delivery_usd,
        "fee_usd": fee,
        "invoice_amount_usd": total,
        "exchange_rates_cup_per_unit": rates,
        "quoted_at": to_utc_naive(utc_now()),
    }


async def _seller_order(seller_id: str, order_id: str) -> dict[str, Any]:
    doc = await get_orders_collection().find_one({
        "_id": _oid(order_id, "Pedido no encontrado."), "seller_id": str(seller_id)
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    if doc.get("payment_method") != "qvapay" or not isinstance(doc.get("qvapay"), dict):
        raise HTTPException(status_code=400, detail="El pedido no usa pago QvaPay.")
    return doc


async def _customer_order(customer_id: str, order_id: str) -> dict[str, Any]:
    doc = await get_orders_collection().find_one({
        "_id": _oid(order_id, "Pedido no encontrado."),
        "buyer_id": str(customer_id),
        "payment_method": "qvapay",
    })
    if not doc or not isinstance(doc.get("qvapay"), dict):
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    return doc


async def _notify_seller(seller_id: str, order_id: str, title: str, content: str, kind: str) -> None:
    seller_oid, order_oid = ObjectId(str(seller_id)), ObjectId(str(order_id))
    document = {
        "_id": ObjectId(), "seller_id": seller_oid, "batch_id": f"{kind}-{order_oid}-{ObjectId()}",
        "kind": kind, "order_id": str(order_oid), "title": title, "content": content,
        "action_label": "Ver pedido", "action_type": "view_orders", "read_at": None,
        "created_at": to_utc_naive(utc_now()), "created_by_admin_id": None,
    }
    from app.database import get_notifications_collection

    await get_notifications_collection().insert_one(document)
    public = SellerNotificationPublic(
        id=str(document["_id"]), title=title, content=content, read_at=None,
        created_at=document["created_at"], kind=kind, action_label="Ver pedido",
        action_type="view_orders", from_admin=False,
    )
    await publish_seller_notification(str(seller_oid), public)
    seller = await get_registrations_collection().find_one({"_id": seller_oid}, {"phone": 1})
    phone = "".join(ch for ch in str((seller or {}).get("phone") or "") if ch.isdigit())
    if phone.startswith("53") and len(phone) == 10:
        phone = phone[2:]
    if len(phone) == 8:
        try:
            await send_custom_sms(phone_e164=phone_e164(phone), message=f"Pa' La Jaba: {content}")
        except Exception:
            logger.exception("No se pudo enviar SMS de pago QvaPay a la tienda")


async def _notify_customer(
    customer_id: str,
    order_id: str,
    title: str,
    content: str,
    kind: str,
    *,
    images: list[str] | None = None,
    sms: bool = True,
) -> None:
    customer_oid = _oid(customer_id, "Cliente no encontrado.")
    created_at = to_utc_naive(utc_now())
    stored_images = [image for image in images or [] if isinstance(image, str) and image.strip()]
    document = {
        "_id": ObjectId(), "customer_id": customer_oid, "order_id": str(order_id), "title": title,
        "content": content, "kind": kind, "images": stored_images, "created_at": created_at, "read_at": None,
    }
    await get_customer_notifications_collection().insert_one(document)
    from app.live.hub import publish_customer_notification
    await publish_customer_notification(str(customer_oid), {
        "id": str(document["_id"]), "order_id": str(order_id), "title": title,
        "content": content, "kind": kind, "images": stored_images, "created_at": created_at, "read_at": None,
    })
    if not sms:
        return
    customer = await get_customers_collection().find_one({"_id": customer_oid}, {"phone": 1})
    phone = "".join(ch for ch in str((customer or {}).get("phone") or "") if ch.isdigit())
    if phone.startswith("53") and len(phone) == 10:
        phone = phone[2:]
    if len(phone) == 8:
        try:
            await send_custom_sms(phone_e164=phone_e164(phone), message=f"Pa' La Jaba: {content}")
        except Exception:
            logger.exception("No se pudo enviar SMS de pago QvaPay al cliente")


async def accept_payment_request(seller_id: str, order_id: str, *, delivery_price: float | None, delivery_currency: str | None) -> dict[str, Any]:
    if not qvapay_escrow_configured():
        raise HTTPException(status_code=503, detail="Los cobros protegidos QvaPay no están disponibles ahora.")
    doc = await _seller_order(seller_id, order_id)
    qv = doc["qvapay"]
    if qv.get("request_status") == "accepted" and qv.get("invoice_url"):
        return {"order_id": str(doc["_id"]), "invoice_url": qv["invoice_url"], "invoice_amount_usd": qv["invoice_amount_usd"]}
    if qv.get("request_status") != "pending_seller":
        raise HTTPException(status_code=409, detail="La solicitud ya fue respondida.")
    from app.admin.service import get_platform_settings

    platform = await get_platform_settings()
    quote = payment_quote(
        doc,
        delivery_price,
        delivery_currency,
        fee_percent=platform.transaction_fee_percent,
    )
    seller = await get_registrations_collection().find_one({"_id": _oid(seller_id, "Tienda no encontrada.")})
    if not seller or not seller.get("qvapay_username"):
        raise HTTPException(status_code=409, detail="Configura primero tu usuario QvaPay.")
    claim = await get_orders_collection().find_one_and_update(
        {"_id": doc["_id"], "status": "pending_confirmation", "qvapay.request_status": "pending_seller"},
        {"$set": {"qvapay.request_status": "creating_invoice", "qvapay.quote": quote,
                  "delivery_price": delivery_price, "delivery_currency": delivery_currency or ("CUP" if delivery_price is not None else None),
                  "updated_at": to_utc_naive(utc_now())}},
        return_document=ReturnDocument.AFTER,
    )
    if not claim:
        latest = await _seller_order(seller_id, order_id)
        latest_qv = latest["qvapay"]
        if latest_qv.get("invoice_url"):
            return {"order_id": str(latest["_id"]), "invoice_url": latest_qv["invoice_url"], "invoice_amount_usd": latest_qv["invoice_amount_usd"]}
        raise HTTPException(status_code=409, detail="La solicitud ya está siendo procesada.")
    try:
        invoice_products = [
            {
                "name": item["name"],
                "quantity": item.get("quantity", 1),
                "price": round(_usd(float(item["line_total"]), item["currency"], quote["exchange_rates_cup_per_unit"]), 2),
            }
            for item in doc.get("items", [])
        ]
        if quote["delivery_amount_usd"] > 0:
            invoice_products.append({"name": "Domicilio", "price": quote["delivery_amount_usd"]})
        if quote["fee_usd"] > 0:
            invoice_products.append({"name": "fee", "price": quote["fee_usd"], "is_fee": True})
        invoice = await create_invoice(
            amount=quote["invoice_amount_usd"],
            description=f"Pedido {str(doc['_id'])[-6:].upper()}, {doc['store_name']}",
            remote_id=f"store-order-{doc['_id']}",
            products=invoice_products,
        )
    except Exception:
        await get_orders_collection().update_one(
            {"_id": doc["_id"], "qvapay.request_status": "creating_invoice"},
            {"$set": {"qvapay.request_status": "pending_seller", "qvapay.payment_status": "not_invoiced"}},
        )
        raise
    qv_update = {**quote, "request_status": "accepted", "payment_status": "awaiting_payment",
                 "invoice_url": invoice.url, "invoice_uuid": invoice.transaction_uuid,
                 "invoice_remote_id": invoice.remote_id, "release_status": "held",
                 "payout_username": seller["qvapay_username"]}
    if doc.get("qvapay", {}).get("buyer_username"):
        qv_update["buyer_username"] = doc["qvapay"]["buyer_username"]
    await get_orders_collection().update_one(
        {"_id": doc["_id"], "qvapay.request_status": "creating_invoice"},
        {"$set": {"qvapay": qv_update, "updated_at": to_utc_naive(utc_now())}},
    )
    await _notify_customer(doc["buyer_id"], str(doc["_id"]), "La tienda aceptó tu pago",
                           f"La tienda aceptó el pedido. Paga la factura QvaPay: {invoice.url}", "qvapay_invoice")
    from app.live.hub import publish_seller_data_update
    await publish_seller_data_update(seller_id, "orders")
    return {"order_id": str(doc["_id"]), "invoice_url": invoice.url, "invoice_amount_usd": quote["invoice_amount_usd"]}


async def reject_payment_request(seller_id: str, order_id: str) -> None:
    doc = await _seller_order(seller_id, order_id)
    result = await get_orders_collection().update_one(
        {"_id": doc["_id"], "status": "pending_confirmation", "qvapay.request_status": "pending_seller"},
        {"$set": {"status": "cancelled", "qvapay.request_status": "rejected", "qvapay.payment_status": "rejected",
                  "cancelled_at": to_utc_naive(utc_now()), "updated_at": to_utc_naive(utc_now())}},
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="La solicitud ya fue respondida.")
    await _notify_customer(doc["buyer_id"], str(doc["_id"]), "Pedido no aceptado", "La tienda rechazó la solicitud de pago QvaPay.", "qvapay_rejected")
    from app.live.hub import publish_seller_data_update
    await publish_seller_data_update(seller_id, "orders")


async def mark_qvapay_invoice_paid(*, remote_id: str | None, transaction_uuid: str | None, status_value: str) -> bool:
    if not remote_id or not remote_id.startswith("store-order-"):
        return False
    try:
        order_oid = ObjectId(remote_id.removeprefix("store-order-"))
    except Exception:
        return False
    doc = await get_orders_collection().find_one({"_id": order_oid, "payment_method": "qvapay"})
    if not doc or not isinstance(doc.get("qvapay"), dict):
        return False
    qv = doc["qvapay"]
    if qv.get("invoice_remote_id") != remote_id or (transaction_uuid and qv.get("invoice_uuid") != transaction_uuid):
        return False
    state = str(status_value or "").lower()
    if state in {"cancelled", "canceled", "expired"}:
        result = await get_orders_collection().update_one(
            {"_id": order_oid, "qvapay.payment_status": "awaiting_payment"},
            {"$set": {"qvapay.payment_status": "cancelled", "updated_at": to_utc_naive(utc_now())}},
        )
        if result.modified_count:
            latest = await get_orders_collection().find_one({"_id": order_oid})
            order_code = str(order_oid)[-6:].upper()
            await _notify_seller(latest["seller_id"], str(order_oid), "Factura QvaPay cancelada",
                                 f"La factura del pedido #{order_code} venció o fue cancelada.", "qvapay_invoice_cancelled")
            await _notify_customer(latest["buyer_id"], str(order_oid), "Factura QvaPay cancelada",
                                   f"La factura del pedido #{order_code} venció o fue cancelada.", "qvapay_invoice_cancelled")
            from app.live.hub import publish_seller_data_update
            await publish_seller_data_update(latest["seller_id"], "orders")
        return result.modified_count > 0
    if state != "paid":
        return False
    result = await get_orders_collection().update_one(
        {"_id": order_oid, "qvapay.payment_status": "awaiting_payment"},
        {"$set": {"qvapay.payment_status": "paid", "qvapay.paid_at": to_utc_naive(utc_now()),
                  "qvapay.release_status": "held", "updated_at": to_utc_naive(utc_now())}},
    )
    if result.modified_count:
        doc = await get_orders_collection().find_one({"_id": order_oid})
        await _notify_seller(doc["seller_id"], str(order_oid), "Pago QvaPay recibido",
                             f"El pedido #{str(order_oid)[-6:].upper()} fue pagado. Prepara y envía la evidencia de entrega.", "qvapay_paid")
        await _notify_customer(doc["buyer_id"], str(order_oid), "Pago recibido",
                               "QvaPay confirmó tu pago. La tienda preparará la entrega.", "qvapay_paid")
        from app.live.hub import publish_seller_data_update
        await publish_seller_data_update(doc["seller_id"], "orders")
    return True


def _safe_evidence_content(content: dict[str, Any]) -> dict[str, Any]:
    try:
        if len(json.dumps(content, ensure_ascii=False)) > 50_000:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="La evidencia excede el tamaño permitido.") from exc
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "image":
                src = str((node.get("attrs") or {}).get("src") or "")
                parsed = urlparse(src)
                if not (src.startswith("/uploads/order-evidence/") or parsed.hostname in {"res.cloudinary.com", "media.qvapay.com"}):
                    raise HTTPException(status_code=400, detail="La imagen de evidencia no es válida.")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(content)
    return content


async def upload_evidence_image(seller_id: str, order_id: str, file: UploadFile) -> dict[str, str]:
    await _seller_order(seller_id, order_id)
    content, content_type = await read_image_upload(file)
    stored = await store_image(content, content_type, scope="order-evidence", owner_id=seller_id)
    return {"url": stored.url}


async def submit_evidence(seller_id: str, order_id: str, content: dict[str, Any]) -> dict[str, Any]:
    doc = await _seller_order(seller_id, order_id)
    qv = doc["qvapay"]
    if qv.get("payment_status") != "paid" or qv.get("release_status") != "held" or doc.get("status") != "pending_confirmation":
        raise HTTPException(status_code=409, detail="El pago debe confirmarse antes de enviar evidencia.")
    evidence = qv.get("evidence") or {}
    if evidence.get("status") == "pending":
        raise HTTPException(status_code=409, detail="El cliente debe responder la evidencia anterior.")
    clean = _safe_evidence_content(content)
    now = to_utc_naive(utc_now())
    evidence = {"content": clean, "status": "pending", "sent_at": now, "deadline": now + EVIDENCE_WINDOW}
    stored = qv.get("evidence")
    previous = stored if isinstance(stored, dict) and stored.get("content") else None
    update: dict[str, Any] = {"$set": {"qvapay.evidence": evidence, "updated_at": now}}
    if previous:
        update["$push"] = {"qvapay.evidence_history": previous}
    result = await get_orders_collection().update_one(
        {"_id": doc["_id"], "status": "pending_confirmation", "qvapay.payment_status": "paid",
         "qvapay.release_status": "held",
         "qvapay.evidence.status": {"$ne": "pending"}},
        update,
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="El cliente debe responder la evidencia anterior.")
    warning = EVIDENCE_WARNING
    await _notify_customer(doc["buyer_id"], str(doc["_id"]), "Evidencia de entrega disponible",
                           f"La tienda envió evidencia. Tienes 48 horas para responder. {warning}", "qvapay_evidence")
    from app.live.hub import publish_seller_data_update
    await publish_seller_data_update(seller_id, "orders")
    return {"evidence": evidence, "warning": warning}


async def _release_funds(order_id: ObjectId) -> None:
    doc = await get_orders_collection().find_one({"_id": order_id, "payment_method": "qvapay"})
    if not doc:
        return
    qv = doc.get("qvapay") or {}
    evidence = qv.get("evidence") or {}
    if qv.get("payment_status") != "paid" or evidence.get("status") not in {"accepted", "expired"}:
        return
    if qv.get("release_status") == "released":
        return
    payout_username = qv.get("payout_username")
    if not payout_username:
        seller = await get_registrations_collection().find_one({"_id": _oid(doc["seller_id"], "Tienda no encontrada.")})
        payout_username = (seller or {}).get("qvapay_username")
    if not payout_username:
        return
    claim = await get_orders_collection().update_one(
        {"_id": order_id, "qvapay.payment_status": "paid", "qvapay.evidence.status": evidence["status"],
         "qvapay.release_status": {"$in": ["held", "retry"]}},
        {"$set": {"qvapay.release_status": "transferring", "updated_at": to_utc_naive(utc_now())}},
    )
    if claim.modified_count != 1:
        return
    qv = doc["qvapay"]
    amount = round(float(qv.get("products_amount_usd", 0)) + float(qv.get("delivery_amount_usd", 0)), 2)
    try:
        transaction = await transfer_to_user(
            amount=amount, username=payout_username,
            description=f"Liquidación pedido {str(order_id)[-6:].upper()}",
            idempotency_key=f"store-order-{order_id}-release",
        )
    except Exception:
        logger.exception("No se pudo liberar QvaPay del pedido %s", order_id)
        await get_orders_collection().update_one(
            {"_id": order_id, "qvapay.release_status": "transferring"},
            {"$set": {"qvapay.release_status": "retry", "updated_at": to_utc_naive(utc_now())}},
        )
        return
    now = to_utc_naive(utc_now())
    await get_orders_collection().update_one(
        {"_id": order_id, "qvapay.release_status": "transferring"},
        {"$set": {"qvapay.release_status": "released", "qvapay.transfer_id": transaction,
                  "status": "completed", "payment_currency": "USD", "completed_at": now,
                  "updated_at": now, "collected_total": amount}},
    )
    from app.products.utils import bump_products_on_order_completed
    await bump_products_on_order_completed(doc.get("items") or [])
    await _notify_seller(doc["seller_id"], str(order_id), "Pago QvaPay liberado",
                         f"El pago del pedido #{str(order_id)[-6:].upper()} fue transferido a tu cuenta QvaPay.", "qvapay_released")
    await _notify_customer(doc["buyer_id"], str(order_id), "Pedido completado",
                           f"El pago del pedido #{str(order_id)[-6:].upper()} fue liberado a la tienda.", "qvapay_released")
    from app.live.hub import publish_seller_data_update
    await publish_seller_data_update(doc["seller_id"], "orders", "products")


async def customer_evidence_decision(customer_id: str, order_id: str, *, accept: bool) -> dict[str, Any]:
    doc = await _customer_order(customer_id, order_id)
    qv = doc["qvapay"]
    evidence = qv.get("evidence") or {}
    if evidence.get("status") != "pending":
        raise HTTPException(status_code=409, detail="No hay evidencia pendiente de respuesta.")
    now = to_utc_naive(utc_now())
    if evidence.get("deadline") and to_utc_naive(evidence["deadline"]) <= now:
        expired = await get_orders_collection().update_one(
            {"_id": doc["_id"], "qvapay.evidence.status": "pending",
             "qvapay.evidence.sent_at": evidence.get("sent_at"), "qvapay.evidence.deadline": {"$lte": now}},
            {"$set": {"qvapay.evidence.status": "expired", "qvapay.evidence.responded_at": now,
                      "qvapay.release_status": "held", "updated_at": now}},
        )
        if expired.modified_count:
            await _release_funds(doc["_id"])
            return {"accepted": True, "expired": True, "support_url": "https://palajaba.com/soporte"}
        raise HTTPException(status_code=409, detail="El plazo para responder la evidencia ya terminó.")
    next_status = "accepted" if accept else "rejected"
    result = await get_orders_collection().update_one(
        {"_id": doc["_id"], "qvapay.evidence.status": "pending", "qvapay.evidence.sent_at": evidence.get("sent_at")},
        {"$set": {"qvapay.evidence.status": next_status, "qvapay.evidence.responded_at": now,
                  "qvapay.release_status": "held", "updated_at": now}},
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="La evidencia ya fue respondida.")
    if accept:
        order_code = str(doc["_id"])[-6:].upper()
        await _notify_seller(doc["seller_id"], str(doc["_id"]), "Evidencia aceptada",
                             f"El cliente aceptó la evidencia del pedido #{order_code}. Se está procesando la liberación del pago.", "qvapay_evidence_accepted")
        await _notify_customer(doc["buyer_id"], str(doc["_id"]), "Evidencia aceptada",
                               f"Registramos tu aceptación del pedido #{order_code}. Se está procesando la liberación del pago a la tienda.", "qvapay_evidence_accepted")
        from app.live.hub import publish_seller_data_update
        await publish_seller_data_update(doc["seller_id"], "orders")
        await _release_funds(doc["_id"])
        from app.payments.disputes import close_dispute_on_acceptance
        await close_dispute_on_acceptance(str(doc["_id"]))
    else:
        await _notify_seller(doc["seller_id"], str(doc["_id"]), "El cliente rechazó la evidencia",
                             f"El cliente rechazó la evidencia del pedido #{str(doc['_id'])[-6:].upper()}. Revisa el pedido antes de enviar otra.", "qvapay_evidence_rejected")
        await _notify_customer(doc["buyer_id"], str(doc["_id"]), "Evidencia rechazada",
                               f"Tu rechazo de la evidencia del pedido #{str(doc['_id'])[-6:].upper()} fue registrado. El pago sigue retenido mientras contactas a soporte o la tienda prepara otra evidencia.", "qvapay_evidence_rejected")
        from app.live.hub import publish_seller_data_update
        await publish_seller_data_update(doc["seller_id"], "orders")
    return {"accepted": accept, "support_url": "https://palajaba.com/soporte"}


async def expire_due_evidence() -> int:
    now = to_utc_naive(utc_now())
    orders = get_orders_collection()
    cursor = orders.find({"payment_method": "qvapay", "qvapay.payment_status": "paid",
                         "qvapay.evidence.status": "pending", "qvapay.evidence.deadline": {"$lte": now}})
    count = 0
    async for doc in cursor:
        evidence = doc.get("qvapay", {}).get("evidence") or {}
        result = await orders.update_one(
            {"_id": doc["_id"], "qvapay.evidence.status": "pending", "qvapay.evidence.sent_at": evidence.get("sent_at"),
             "qvapay.evidence.deadline": {"$lte": now}},
            {"$set": {"qvapay.evidence.status": "expired", "qvapay.evidence.responded_at": now,
                      "qvapay.release_status": "held", "updated_at": now}},
        )
        if result.modified_count:
            await _release_funds(doc["_id"])
            count += 1
    retry = orders.find({"payment_method": "qvapay", "qvapay.payment_status": "paid",
                         "qvapay.release_status": "retry", "qvapay.evidence.status": {"$in": ["accepted", "expired"]}})
    async for doc in retry:
        await _release_funds(doc["_id"])
    # Recupera el caso de caída del proceso después de reclamar la transferencia.
    stale_transfer_before = now - timedelta(minutes=5)
    await orders.update_many(
        {"payment_method": "qvapay", "qvapay.release_status": "transferring",
         "qvapay.evidence.status": {"$in": ["accepted", "expired"]}, "updated_at": {"$lte": stale_transfer_before}},
        {"$set": {"qvapay.release_status": "retry", "updated_at": now}},
    )
    stale_retry = orders.find({"payment_method": "qvapay", "qvapay.payment_status": "paid",
                               "qvapay.release_status": "retry", "qvapay.evidence.status": {"$in": ["accepted", "expired"]}})
    async for doc in stale_retry:
        await _release_funds(doc["_id"])
    return count


async def _expiry_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await expire_due_evidence()
        except Exception:
            logger.exception("Error al procesar vencimientos de evidencia QvaPay")


def start_expiry_task() -> asyncio.Task:
    global _expiry_task
    if _expiry_task is None or _expiry_task.done():
        _expiry_task = asyncio.create_task(_expiry_loop())
    return _expiry_task


async def stop_expiry_task() -> None:
    global _expiry_task
    if _expiry_task is None:
        return
    _expiry_task.cancel()
    try:
        await _expiry_task
    except asyncio.CancelledError:
        pass
    _expiry_task = None


async def list_customer_notifications(customer_id: str) -> list[dict[str, Any]]:
    docs = await get_customer_notifications_collection().find({"customer_id": _oid(customer_id, "Cliente no encontrado.")}).sort("created_at", -1).limit(50).to_list(length=50)
    return [{"id": str(doc["_id"]), "title": doc["title"], "content": doc["content"], "kind": doc["kind"],
             "images": [image for image in doc.get("images") or [] if isinstance(image, str)],
             "order_id": doc["order_id"], "created_at": doc["created_at"], "read_at": doc.get("read_at")} for doc in docs]


async def mark_customer_notification_read(customer_id: str, notification_id: str) -> dict[str, Any]:
    doc = await get_customer_notifications_collection().find_one_and_update(
        {"_id": _oid(notification_id, "Notificación no encontrada."), "customer_id": _oid(customer_id, "Cliente no encontrado.")},
        {"$set": {"read_at": to_utc_naive(utc_now())}}, return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Notificación no encontrada.")
    return {"id": str(doc["_id"]), "title": doc["title"], "content": doc["content"], "kind": doc["kind"],
            "images": [image for image in doc.get("images") or [] if isinstance(image, str)],
            "order_id": doc["order_id"], "created_at": doc["created_at"], "read_at": doc.get("read_at")}
