"""Una disputa por pedido de evidencia QvaPay rechazada."""

from __future__ import annotations

import logging
from typing import Any, Literal
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.database import (
    get_catalog_products_collection,
    get_customers_collection,
    get_disputes_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.payments.qvapay import transfer_to_user
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug

logger = logging.getLogger(__name__)

Party = Literal["buyer", "seller"]
Winner = Literal["buyer", "seller"]
ACCEPTANCE_REASON = "El comprador aceptó la evidencia."


async def ensure_dispute_indexes() -> None:
    collection = get_disputes_collection()
    await collection.create_index("order_id", unique=True)
    await collection.create_index("status")


def _oid(value: str, message: str) -> ObjectId:
    try:
        return ObjectId(str(value).strip())
    except Exception as exc:
        raise HTTPException(status_code=404, detail=message) from exc


def _public(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "order_id": str(doc["order_id"]),
        "status": doc["status"],
        "opened_by": list(doc.get("opened_by") or []),
        "winner": doc.get("winner"),
        "reason": doc.get("reason"),
        "reports": _public_reports(doc.get("reports")),
        "resolution": doc.get("resolution"),
        "created_at": doc.get("created_at"),
        "resolved_at": doc.get("resolved_at"),
    }


def _eligible(order: dict[str, Any]) -> bool:
    qvapay = order.get("qvapay") if isinstance(order.get("qvapay"), dict) else {}
    evidence = qvapay.get("evidence") if isinstance(qvapay.get("evidence"), dict) else {}
    return (
        order.get("payment_method") == "qvapay"
        and qvapay.get("payment_status") == "paid"
        and qvapay.get("release_status") == "held"
        and evidence.get("status") == "rejected"
    )


async def _order_for_party(order_id: str, party: Party, actor_id: str) -> dict[str, Any]:
    order = await get_orders_collection().find_one({"_id": _oid(order_id, "Pedido no encontrado.")})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    if party == "buyer" and str(order.get("buyer_id") or "") != str(actor_id):
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    if party == "seller" and str(order.get("seller_id") or "") != str(actor_id):
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    return order


def _public_reports(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reports = []
    for item in value:
        if not isinstance(item, dict) or item.get("party") not in {"buyer", "seller"}:
            continue
        reports.append({
            "party": item.get("party"),
            "text": item.get("text") or "",
            "images": [str(src) for src in item.get("images") or [] if src],
            "created_at": item.get("created_at"),
        })
    return reports


def _clean_report_images(images: list[str]) -> list[str]:
    clean = []
    for raw in images:
        src = str(raw or "").strip()
        if not src or ".." in src.split("/"):
            raise HTTPException(status_code=400, detail="La imagen del motivo no es válida.")
        parsed = urlparse(src)
        allowed = src.startswith("/uploads/dispute-reports/") or parsed.hostname == "res.cloudinary.com"
        if not allowed:
            raise HTTPException(status_code=400, detail="La imagen del motivo no es válida.")
        clean.append(src)
    if len(clean) > 6:
        raise HTTPException(status_code=400, detail="Puedes adjuntar hasta 6 imágenes.")
    return clean


def _party_report(party: Party, text: str, images: list[str], now) -> dict[str, Any]:
    return {"party": party, "text": text, "images": images, "created_at": now}


def _party_has_report(dispute: dict[str, Any] | None, party: Party) -> bool:
    reports = dispute.get("reports") if isinstance(dispute, dict) else None
    return any(isinstance(item, dict) and item.get("party") == party for item in reports or [])


def _with_existing_report(dispute: dict[str, Any], party: Party) -> dict[str, Any]:
    public = _public(dispute)
    public["already_reported"] = _party_has_report(dispute, party)
    return public


async def _mark_support_reported(order_id: ObjectId, party: Party, now) -> None:
    field = "qvapay.buyer_support_reported" if party == "buyer" else "qvapay.seller_support_reported"
    await get_orders_collection().update_one({"_id": order_id}, {"$set": {field: True, "updated_at": now}})


async def _save_party_report(order: dict[str, Any], dispute: dict[str, Any], party: Party, report: dict[str, Any], now) -> None:
    reports = [item for item in dispute.get("reports") or [] if isinstance(item, dict)]
    reports.append(report)
    await get_disputes_collection().update_one(
        {"_id": dispute["_id"], "status": "open"},
        {"$addToSet": {"opened_by": party}, "$set": {"reports": reports, "updated_at": now}},
    )
    await _mark_support_reported(order["_id"], party, now)


async def upload_dispute_image(order_id: str, party: Party, actor_id: str, file) -> dict[str, str]:
    from app.catalogs.media_storage import read_image_upload, store_image

    order = await _order_for_party(order_id, party, actor_id)
    existing = await get_disputes_collection().find_one({"order_id": order["_id"]})
    if _party_has_report(existing, party):
        raise HTTPException(status_code=409, detail="Ya enviaste el motivo de esta disputa.")
    if not (existing and existing.get("status") == "open") and not _eligible(order):
        raise HTTPException(status_code=409, detail="No hay una evidencia rechazada con el pago retenido.")
    content, content_type = await read_image_upload(file)
    stored = await store_image(content, content_type, scope="dispute-reports", owner_id=actor_id)
    return {"url": stored.url}


async def open_dispute(order_id: str, party: Party, actor_id: str, *, text: str, images: list[str]) -> dict[str, Any]:
    order = await _order_for_party(order_id, party, actor_id)
    collection = get_disputes_collection()
    existing = await collection.find_one({"order_id": order["_id"]})
    now = to_utc_naive(utc_now())
    if existing and (_party_has_report(existing, party) or existing.get("status") != "open"):
        return _with_existing_report(existing, party)
    report = _party_report(party, text, _clean_report_images(images), now)
    if existing:
        await _save_party_report(order, existing, party, report, now)
        saved = await collection.find_one({"_id": existing["_id"]})
        return _public(saved or existing)
    if not _eligible(order):
        raise HTTPException(status_code=409, detail="No hay una evidencia rechazada con el pago retenido.")
    document = {
        "_id": ObjectId(),
        "order_id": order["_id"],
        "customer_id": str(order.get("buyer_id") or ""),
        "seller_id": str(order.get("seller_id") or ""),
        "opened_by": [party],
        "status": "open",
        "winner": None,
        "reason": None,
        "reports": [report],
        "resolution": None,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }
    try:
        await collection.insert_one(document)
        await _mark_support_reported(order["_id"], party, now)
    except DuplicateKeyError:
        existing = await collection.find_one({"order_id": order["_id"]})
        if existing and existing.get("status") == "open" and not _party_has_report(existing, party):
            await _save_party_report(order, existing, party, report, now)
            existing = await collection.find_one({"_id": existing["_id"]})
        if not existing:
            raise HTTPException(status_code=409, detail="No se pudo abrir la disputa.")
        return _public(existing)
    return _public(document)


async def close_dispute_on_acceptance(order_id: str) -> None:
    now = to_utc_naive(utc_now())
    try:
        order_oid = ObjectId(str(order_id))
    except Exception:
        return
    await get_disputes_collection().update_one(
        {"order_id": order_oid, "status": "open"},
        {"$set": {
            "status": "resolved",
            "resolution": "acceptance",
            "winner": "seller",
            "reason": ACCEPTANCE_REASON,
            "resolved_at": now,
            "updated_at": now,
        }},
    )


async def count_open_disputes() -> int:
    return await get_disputes_collection().count_documents({"status": "open"})


def _parties_label(opened_by: list[str]) -> str:
    parties = set(opened_by)
    if "buyer" in parties and "seller" in parties:
        return "Disputan ambas partes"
    if "seller" in parties:
        return "Disputa la tienda"
    return "Disputa el comprador"


def _order_summary(doc: dict[str, Any], disputed_id: ObjectId) -> dict[str, Any]:
    subtotals = doc.get("subtotals") or []
    total = ""
    if subtotals and isinstance(subtotals[0], dict):
        total = f"{subtotals[0].get('amount')} {subtotals[0].get('currency') or ''}".strip()
    qvapay = doc.get("qvapay") if isinstance(doc.get("qvapay"), dict) else {}
    evidence = qvapay.get("evidence") if isinstance(qvapay.get("evidence"), dict) else {}
    items = []
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append({
            "name": item.get("name") or "",
            "quantity": item.get("quantity") or 0,
            "unit_price": item.get("unit_price"),
            "currency": item.get("currency") or "",
            "line_total": item.get("line_total"),
        })
    delivery = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else None
    return {
        "id": str(doc["_id"]),
        "code": str(doc["_id"])[-6:].upper(),
        "created_at": doc.get("created_at"),
        "status": doc.get("status"),
        "store_name": doc.get("store_name") or "",
        "buyer_name": doc.get("buyer_name") or "",
        "buyer_phone": doc.get("buyer_phone") or "",
        "payment_method": doc.get("payment_method") or "contact",
        "payment_currency": doc.get("payment_currency") or "",
        "origin": doc.get("origin") or "platform",
        "total": total,
        "subtotals": subtotals if isinstance(subtotals, list) else [],
        "items": items,
        "delivery_requested": bool(doc.get("delivery_requested")),
        "delivery": delivery,
        "delivery_price": doc.get("delivery_price"),
        "delivery_currency": doc.get("delivery_currency") or "",
        "evidence_status": evidence.get("status"),
        "release_status": qvapay.get("release_status"),
        "disputed": doc["_id"] == disputed_id,
    }


def _product_status(doc: dict[str, Any]) -> str:
    if doc.get("deleted_at"):
        return "borrado"
    if not doc.get("is_available", True):
        return "agotado"
    return "publico"


def _product_image(doc: dict[str, Any]) -> str:
    images = doc.get("images") or []
    frontal = next((image for image in images if isinstance(image, dict) and image.get("is_frontal") and image.get("image_url")), None)
    any_image = next((image for image in images if isinstance(image, dict) and image.get("image_url")), None)
    return str((frontal or any_image or {}).get("image_url") or doc.get("image_url") or "")


async def list_disputes() -> list[dict[str, Any]]:
    docs = await get_disputes_collection().find({}).sort([("status", 1), ("created_at", -1)]).to_list(length=200)
    if not docs:
        return []
    order_ids = [doc["order_id"] for doc in docs if isinstance(doc.get("order_id"), ObjectId)]
    orders = await get_orders_collection().find({"_id": {"$in": order_ids}}).to_list(length=len(order_ids))
    orders_by_id = {doc["_id"]: doc for doc in orders}
    customer_ids = []
    for doc in docs:
        try:
            customer_ids.append(ObjectId(doc.get("customer_id")))
        except Exception:
            continue
    customers = await get_customers_collection().find({"_id": {"$in": customer_ids}}, {"full_name": 1}).to_list(length=len(customer_ids) or 1)
    names = {str(doc["_id"]): doc.get("full_name") or "" for doc in customers}
    rows = []
    for doc in docs:
        order = orders_by_id.get(doc.get("order_id")) or {}
        rows.append({
            **_public(doc),
            "order_code": str(doc["order_id"])[-6:].upper(),
            "store_name": order.get("store_name") or "",
            "buyer_name": names.get(str(doc.get("customer_id") or ""), order.get("buyer_name") or ""),
            "parties_label": _parties_label(list(doc.get("opened_by") or [])),
        })
    rows.sort(key=lambda item: (item["status"] != "open",))
    return rows


async def agreement_pdf(dispute_id: str, kind: str) -> tuple[bytes, str]:
    import asyncio

    from app.payments.dispute_report import AGREEMENT_DOCUMENTS, build_agreement_pdf

    if kind not in AGREEMENT_DOCUMENTS:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    dispute = await get_disputes_collection().find_one({"_id": _oid(dispute_id, "Disputa no encontrada.")})
    if not dispute:
        raise HTTPException(status_code=404, detail="Disputa no encontrada.")
    order = await get_orders_collection().find_one({"_id": dispute["order_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    seller = None
    try:
        seller = await get_registrations_collection().find_one({"_id": ObjectId(str(order.get("seller_id") or ""))})
    except Exception:
        seller = None
    return await asyncio.to_thread(
        build_agreement_pdf,
        order,
        kind,
        store_name=(seller or {}).get("store_name") or order.get("store_name") or "",
    )


async def get_dispute_detail(dispute_id: str) -> dict[str, Any]:
    dispute = await get_disputes_collection().find_one({"_id": _oid(dispute_id, "Disputa no encontrada.")})
    if not dispute:
        raise HTTPException(status_code=404, detail="Disputa no encontrada.")
    order = await get_orders_collection().find_one({"_id": dispute["order_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    customer = None
    try:
        customer = await get_customers_collection().find_one({"_id": ObjectId(str(dispute.get("customer_id") or ""))})
    except Exception:
        customer = None
    seller = None
    try:
        seller = await get_registrations_collection().find_one({"_id": ObjectId(str(order.get("seller_id") or ""))})
    except Exception:
        seller = None
    buyer_orders = await get_orders_collection().find({"buyer_id": str(order.get("buyer_id") or "")}).sort("created_at", -1).to_list(length=300)
    seller_orders = await get_orders_collection().find({"seller_id": str(order.get("seller_id") or "")}).sort("created_at", -1).to_list(length=300)
    products = await get_catalog_products_collection().find({"seller_id": str(order.get("seller_id") or "")}).sort("name", 1).to_list(length=500)
    slug = ""
    if seller:
        slug = str(seller.get("store_slug") or store_name_to_slug(str(seller.get("store_name") or "")) or "")
    qvapay = order.get("qvapay") if isinstance(order.get("qvapay"), dict) else {}
    return {
        **_public(dispute),
        "order_code": str(order["_id"])[-6:].upper(),
        "parties_label": _parties_label(list(dispute.get("opened_by") or [])),
        "buyer_username": qvapay.get("buyer_username") or (customer or {}).get("qvapay_username"),
        "buyer": {
            "full_name": (customer or {}).get("full_name") or order.get("buyer_name") or "",
            "phone": (customer or {}).get("phone") or order.get("buyer_phone") or "",
            "identity_card": (customer or {}).get("identity_card") or "",
            "email": (customer or {}).get("email") or order.get("buyer_email") or "",
            "profile_photo_url": (customer or {}).get("profile_photo_url"),
            "orders": [_order_summary(item, order["_id"]) for item in buyer_orders],
        },
        "store": {
            "name": (seller or {}).get("store_name") or order.get("store_name") or "",
            "phone": (seller or {}).get("phone") or "",
            "email": (seller or {}).get("email") or "",
            "sales_url": f"/{slug}" if slug else "",
            "products": [
                {
                    "id": str(item["_id"]),
                    "name": item.get("name") or "",
                    "status": _product_status(item),
                    "image_url": _product_image(item),
                }
                for item in products
            ],
            "orders": [_order_summary(item, order["_id"]) for item in seller_orders],
        },
        "order": _order_summary(order, order["_id"]),
        "evidence_status": (qvapay.get("evidence") or {}).get("status") if isinstance(qvapay.get("evidence"), dict) else None,
        "release_status": qvapay.get("release_status"),
    }


async def _buyer_qvapay_username(order: dict[str, Any]) -> str:
    buyer_id = str(order.get("buyer_id") or "").strip()
    if not buyer_id:
        return ""
    try:
        customer = await get_customers_collection().find_one(
            {"_id": ObjectId(buyer_id)},
            {"qvapay_username": 1},
        )
    except Exception:
        return ""
    return str((customer or {}).get("qvapay_username") or "").strip()


def _money(order: dict[str, Any], *, refund: bool) -> tuple[float, str]:
    qvapay = order.get("qvapay") or {}
    if refund:
        amount = qvapay.get("invoice_amount_usd")
        if amount is None:
            amount = float(qvapay.get("products_amount_usd") or 0) + float(qvapay.get("delivery_amount_usd") or 0)
        username = str(qvapay.get("buyer_username") or "").strip()
        return round(float(amount or 0), 2), username
    amount = round(float(qvapay.get("products_amount_usd") or 0) + float(qvapay.get("delivery_amount_usd") or 0), 2)
    username = str(qvapay.get("payout_username") or "").strip()
    return amount, username


async def _notify_resolution(order: dict[str, Any], reason: str) -> None:
    from app.payments.service import _notify_customer, _notify_seller

    order_id = str(order["_id"])
    title = "Resolución de tu disputa"
    await _notify_seller(order["seller_id"], order_id, title, reason, "dispute_resolved")
    await _notify_customer(order["buyer_id"], order_id, title, reason, "dispute_resolved")


async def _resolve(dispute_id: ObjectId, *, winner: Winner, reason: str, resolution: str) -> None:
    now = to_utc_naive(utc_now())
    await get_disputes_collection().update_one(
        {"_id": dispute_id, "status": "open"},
        {"$set": {
            "status": "resolved",
            "winner": winner,
            "reason": reason,
            "resolution": resolution,
            "resolved_at": now,
            "updated_at": now,
        }},
    )


async def rule_dispute(dispute_id: str, *, winner: Winner, reason: str) -> dict[str, Any]:
    dispute = await get_disputes_collection().find_one({"_id": _oid(dispute_id, "Disputa no encontrada.")})
    if not dispute:
        raise HTTPException(status_code=404, detail="Disputa no encontrada.")
    if dispute.get("status") != "open":
        raise HTTPException(status_code=409, detail="La disputa ya fue resuelta.")
    order = await get_orders_collection().find_one({"_id": dispute["order_id"]})
    if not order or not isinstance(order.get("qvapay"), dict):
        raise HTTPException(status_code=409, detail="El pedido no tiene un pago QvaPay.")
    qvapay = order["qvapay"]
    release_status = qvapay.get("release_status")
    if winner == "seller" and release_status == "released":
        await _resolve(dispute["_id"], winner="seller", reason=reason, resolution="admin")
        await _notify_resolution(order, reason)
        fresh = await get_disputes_collection().find_one({"_id": dispute["_id"]})
        return _public(fresh)
    if winner == "buyer" and release_status == "refunded":
        await _resolve(dispute["_id"], winner="buyer", reason=reason, resolution="admin")
        await _notify_resolution(order, reason)
        fresh = await get_disputes_collection().find_one({"_id": dispute["_id"]})
        return _public(fresh)
    if release_status == "released":
        raise HTTPException(status_code=409, detail="El pago ya fue liberado a la tienda.")
    if release_status == "refunded":
        raise HTTPException(status_code=409, detail="El pago ya fue devuelto al comprador.")
    if release_status == "transferring":
        raise HTTPException(status_code=409, detail="El pago se está transfiriendo.")

    previous_evidence = (qvapay.get("evidence") or {}).get("status") if isinstance(qvapay.get("evidence"), dict) else None
    amount, username = _money(order, refund=winner == "buyer")
    if winner == "buyer":
        username = await _buyer_qvapay_username(order) or username
    if winner == "seller" and not username:
        seller = await get_registrations_collection().find_one({"_id": _oid(order["seller_id"], "Tienda no encontrada.")})
        username = str((seller or {}).get("qvapay_username") or "").strip()
    if winner == "buyer" and not username:
        raise HTTPException(status_code=409, detail="El comprador no tiene un usuario QvaPay.")
    if not username or amount <= 0:
        raise HTTPException(status_code=409, detail="No hay un destino o un monto para transferir.")

    now = to_utc_naive(utc_now())
    claim_set: dict[str, Any] = {"qvapay.release_status": "transferring", "updated_at": now}
    if winner == "seller":
        claim_set["qvapay.evidence.status"] = "accepted"
    else:
        claim_set["qvapay.buyer_username"] = username
    claim = await get_orders_collection().update_one(
        {"_id": order["_id"], "qvapay.payment_status": "paid", "qvapay.release_status": {"$in": ["held", "retry"]}},
        {"$set": claim_set},
    )
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="El pago ya no está retenido.")
    idempotency = f"store-order-{order['_id']}-{'refund' if winner == 'buyer' else 'release'}"
    description = f"{'Devolución' if winner == 'buyer' else 'Liquidación'} pedido {str(order['_id'])[-6:].upper()}"
    try:
        transaction = await transfer_to_user(
            amount=amount,
            username=username,
            description=description,
            idempotency_key=idempotency,
        )
    except Exception:
        logger.exception("No se pudo transferir la disputa %s", dispute_id)
        restore = {"qvapay.release_status": "held", "updated_at": to_utc_naive(utc_now())}
        if winner == "seller" and previous_evidence:
            restore["qvapay.evidence.status"] = previous_evidence
        await get_orders_collection().update_one(
            {"_id": order["_id"], "qvapay.release_status": "transferring"},
            {"$set": restore},
        )
        raise HTTPException(status_code=503, detail="No pudimos mover el pago. La disputa sigue abierta.")

    finished = to_utc_naive(utc_now())
    if winner == "seller":
        await get_orders_collection().update_one(
            {"_id": order["_id"], "qvapay.release_status": "transferring"},
            {"$set": {
                "qvapay.release_status": "released",
                "qvapay.transfer_id": transaction,
                "status": "completed",
                "payment_currency": "USD",
                "completed_at": finished,
                "updated_at": finished,
                "collected_total": amount,
            }},
        )
        from app.products.utils import bump_products_on_order_completed
        await bump_products_on_order_completed(order.get("items") or [])
    else:
        await get_orders_collection().update_one(
            {"_id": order["_id"], "qvapay.release_status": "transferring"},
            {"$set": {
                "qvapay.release_status": "refunded",
                "qvapay.payment_status": "refunded",
                "qvapay.refund_transfer_id": transaction,
                "qvapay.evidence.status": "closed",
                "status": "cancelled",
                "cancelled_at": finished,
                "updated_at": finished,
            }},
        )
    await _resolve(dispute["_id"], winner=winner, reason=reason, resolution="admin")
    latest = await get_orders_collection().find_one({"_id": order["_id"]})
    await _notify_resolution(latest or order, reason)
    from app.live.hub import publish_seller_data_update
    await publish_seller_data_update(str(order["seller_id"]), "orders")
    fresh = await get_disputes_collection().find_one({"_id": dispute["_id"]})
    return _public(fresh)
