"""Cobros QvaPay de altas, renovaciones y cambios de plan."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.database import (
    get_registrations_collection,
    get_subscription_qvapay_purchases_collection,
)
from app.payments.qvapay import create_invoice, qvapay_configured
from app.exchange_rates.service import snapshot_cup_per_unit
from app.admin.service import get_plan_prices, get_platform_settings
from app.subscriptions.plugins import normalize_plugin_selection, plugins_total_usd, seller_has_plugin
from app.subscriptions.service import (
    expiry_notice_reset,
    is_subscription_active,
    normalize_billing_period,
    normalize_plan_tier,
    record_subscription_payment,
)
from app.subscriptions.utils import subscription_period_end
from app.utils.datetime import to_utc_naive, utc_now


def _oid(value: str, message: str) -> ObjectId:
    try:
        return ObjectId(str(value).strip())
    except Exception as exc:
        raise HTTPException(status_code=404, detail=message) from exc


def _discounted_usd(amount_usd: float, percent: float) -> float:
    rate = Decimal(str(percent or 0))
    if rate <= 0:
        return amount_usd
    if rate > 100:
        rate = Decimal("100")
    discounted = (Decimal(str(amount_usd)) * (Decimal("100") - rate) / Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    if discounted <= 0:
        raise HTTPException(status_code=400, detail="El descuento deja el plan en cero.")
    return float(discounted)


async def _qvapay_plan_discount_percent() -> float:
    from app.admin.service import get_platform_settings

    settings = await get_platform_settings()
    return float(getattr(settings, "qvapay_plan_discount_percent", 0) or 0)


def _usd_amount(amount: float, currency: str, rates: dict[str, float]) -> float:
    if currency in {"USD", "QUSD"}:
        raw = float(amount)
    else:
        source_rate = rates.get(currency)
        usd_rate = rates.get("USD")
        if not source_rate or not usd_rate:
            raise HTTPException(status_code=503, detail=f"No hay tasa disponible para {currency}.")
        raw = float(amount) * float(source_rate) / float(usd_rate)
    rounded = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded <= 0:
        raise HTTPException(status_code=400, detail="El precio del plan debe ser mayor que cero.")
    return float(rounded)


async def ensure_subscription_qvapay_indexes() -> None:
    collection = get_subscription_qvapay_purchases_collection()
    await collection.create_index("seller_id")
    indexes = await collection.index_information()
    remote = indexes.get("remote_id_1")
    if remote is None or not remote.get("sparse"):
        if remote is not None:
            await collection.drop_index("remote_id_1")
        await collection.create_index("remote_id", unique=True, sparse=True)
    await collection.create_index("transaction_uuid", unique=True, sparse=True)
    await collection.create_index([("seller_id", 1), ("status", 1), ("created_at", -1)])


def _checkout_public(
    doc: dict[str, Any], *, include_plan_amount: bool = False, payment_url: str = ""
) -> dict[str, Any]:
    result = {
        "purchase_id": str(doc["_id"]),
        "plan_tier": doc["plan_tier"],
        "billing_period": doc["billing_period"],
        "invoice_amount_usd": float(doc["invoice_amount_usd"]),
        "payment_url": payment_url,
        "status": str(doc["status"]),
    }
    if include_plan_amount:
        result["plan_amount_usd"] = float(doc["plan_amount_usd"])
    return result


async def create_subscription_plan_checkout(
    *, seller_id: str, plan_tier: str, billing_period: str
) -> dict[str, Any]:
    if not qvapay_configured():
        raise HTTPException(status_code=503, detail="Los pagos QvaPay no están disponibles ahora.")

    seller_oid = _oid(seller_id, "Tienda no encontrada.")
    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if not seller or seller.get("status") not in {"approved", "expired"}:
        raise HTTPException(status_code=403, detail="La tienda no puede pagar un plan ahora.")
    if not seller.get("is_trial") and is_subscription_active(seller):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tu plan actual sigue activo. Podrás pagar otro plan cuando venza.",
        )

    tier = normalize_plan_tier(plan_tier)
    period = normalize_billing_period(billing_period)
    purchases = get_subscription_qvapay_purchases_collection()

    rates = snapshot_cup_per_unit()
    configured_price = (await get_plan_prices()).get_price(tier, period)
    plan_amount_usd = _usd_amount(configured_price.amount, configured_price.currency, rates)
    discount_percent = await _qvapay_plan_discount_percent()
    invoice_amount_usd = _discounted_usd(plan_amount_usd, discount_percent)
    now = to_utc_naive(utc_now())
    purchase_id = ObjectId()
    remote_id = f"subscription-plan-{purchase_id}"
    document = {
        "_id": purchase_id,
        "remote_id": remote_id,
        "seller_id": str(seller_oid),
        "store_name": str(seller.get("store_name") or "Tienda"),
        "plan_tier": tier,
        "billing_period": period,
        "plan_amount_usd": plan_amount_usd,
        "discount_percent": discount_percent,
        "invoice_amount_usd": invoice_amount_usd,
        "currency": "USD",
        "exchange_rates_cup_per_unit": rates,
        "status": "creating_invoice",
        "created_at": now,
        "updated_at": now,
    }
    await purchases.insert_one(document)

    try:
        invoice = await create_invoice(
            amount=invoice_amount_usd,
            description=f"Plan {tier.title()} {period}, {document['store_name']}",
            remote_id=remote_id,
        )
    except Exception:
        await purchases.update_one(
            {"_id": purchase_id, "status": "creating_invoice"},
            {"$set": {"status": "failed", "updated_at": to_utc_naive(utc_now())}},
        )
        raise

    await purchases.update_one(
        {"_id": purchase_id, "status": "creating_invoice"},
        {
            "$set": {
                "transaction_uuid": invoice.transaction_uuid,
                "status": "pending",
                "updated_at": to_utc_naive(utc_now()),
            }
        },
    )
    document.update(
        {
            "transaction_uuid": invoice.transaction_uuid,
            "status": "pending",
        }
    )
    return _checkout_public(document, include_plan_amount=True, payment_url=invoice.url)


async def create_initial_subscription_checkout(*, plan_tier: str, billing_period: str) -> dict[str, Any]:
    if not qvapay_configured():
        raise HTTPException(status_code=503, detail="Los pagos QvaPay no están disponibles ahora.")
    tier = normalize_plan_tier(plan_tier)
    period = normalize_billing_period(billing_period)
    rates = snapshot_cup_per_unit()
    configured_price = (await get_plan_prices()).get_price(tier, period)
    amount_usd = _usd_amount(configured_price.amount, configured_price.currency, rates)
    discount_percent = await _qvapay_plan_discount_percent()
    invoice_amount_usd = _discounted_usd(amount_usd, discount_percent)
    now = to_utc_naive(utc_now())
    purchase_id = ObjectId()
    remote_id = f"subscription-plan-{purchase_id}"
    document = {
        "_id": purchase_id,
        "remote_id": remote_id,
        "seller_id": None,
        "store_name": "Nueva tienda",
        "plan_tier": tier,
        "billing_period": period,
        "plan_amount_usd": amount_usd,
        "discount_percent": discount_percent,
        "invoice_amount_usd": invoice_amount_usd,
        "currency": "USD",
        "exchange_rates_cup_per_unit": rates,
        "status": "creating_invoice",
        "created_at": now,
        "updated_at": now,
    }
    purchases = get_subscription_qvapay_purchases_collection()
    await purchases.insert_one(document)
    try:
        invoice = await create_invoice(
            amount=invoice_amount_usd,
            description=f"Plan {tier.title()} {period}, Alta de tienda",
            remote_id=remote_id,
        )
    except Exception:
        await purchases.update_one(
            {"_id": purchase_id, "status": "creating_invoice"},
            {"$set": {"status": "failed", "updated_at": to_utc_naive(utc_now())}},
        )
        raise
    document.update({"transaction_uuid": invoice.transaction_uuid, "status": "pending"})
    await purchases.update_one(
        {"_id": purchase_id, "status": "creating_invoice"},
        {"$set": {"transaction_uuid": invoice.transaction_uuid, "status": "pending", "updated_at": to_utc_naive(utc_now())}},
    )
    return _checkout_public(document, include_plan_amount=True, payment_url=invoice.url)


async def quote_custom_selection(
    plugins: dict,
    billing_period: str,
    *,
    customers_included: bool = False,
) -> tuple[dict[str, int], str, float, float]:
    period = normalize_billing_period(billing_period)
    selection = normalize_plugin_selection(plugins, customers_included=customers_included)
    if not selection:
        raise HTTPException(status_code=400, detail="Elige al menos una función.")
    stored = await get_platform_settings()
    prices = stored.plugin_prices.model_dump()
    amount_usd = plugins_total_usd(prices, selection, period)
    if amount_usd <= 0:
        raise HTTPException(status_code=400, detail="El plan personalizado no tiene un precio.")
    discount_percent = await _qvapay_plan_discount_percent()
    return selection, period, amount_usd, discount_percent


def _custom_public(document: dict[str, Any], payment_url: str = "") -> dict[str, Any]:
    return {
        "purchase_id": str(document["_id"]),
        "plan_tier": "custom",
        "billing_period": document.get("billing_period"),
        "plan_plugins": document.get("plan_plugins") or {},
        "plan_amount_usd": document.get("plan_amount_usd"),
        "invoice_amount_usd": document.get("invoice_amount_usd"),
        "amount_cup": document.get("payment_amount_cup"),
        "payment_url": payment_url or document.get("payment_url") or "",
        "status": document.get("status"),
        "payment_method": document.get("payment_method") or "qvapay",
        "addon_expires_at": document.get("addon_expires_at"),
        "store_name": document.get("store_name") or "",
        "transfer_id": document.get("transfer_id") or "",
    }


async def create_custom_qvapay_checkout(*, plugins: dict, billing_period: str) -> dict[str, Any]:
    if not qvapay_configured():
        raise HTTPException(status_code=503, detail="Los pagos QvaPay no están disponibles ahora.")
    selection, period, amount_usd, discount_percent = await quote_custom_selection(plugins, billing_period)
    invoice_amount_usd = _discounted_usd(amount_usd, discount_percent)
    rates = snapshot_cup_per_unit()
    now = to_utc_naive(utc_now())
    purchase_id = ObjectId()
    remote_id = f"subscription-plan-{purchase_id}"
    document = {
        "_id": purchase_id,
        "remote_id": remote_id,
        "seller_id": None,
        "store_name": "Nueva tienda",
        "purchase_kind": "custom",
        "plan_tier": "custom",
        "plan_plugins": selection,
        "billing_period": period,
        "plan_amount_usd": amount_usd,
        "discount_percent": discount_percent,
        "invoice_amount_usd": invoice_amount_usd,
        "currency": "USD",
        "payment_method": "qvapay",
        "exchange_rates_cup_per_unit": rates,
        "status": "creating_invoice",
        "created_at": now,
        "updated_at": now,
    }
    purchases = get_subscription_qvapay_purchases_collection()
    await purchases.insert_one(document)
    try:
        invoice = await create_invoice(
            amount=invoice_amount_usd,
            description="Plan personalizado, Alta de tienda",
            remote_id=remote_id,
        )
    except Exception:
        await purchases.update_one(
            {"_id": purchase_id, "status": "creating_invoice"},
            {"$set": {"status": "failed", "updated_at": to_utc_naive(utc_now())}},
        )
        raise
    document.update({"transaction_uuid": invoice.transaction_uuid, "status": "pending", "payment_url": invoice.url})
    await purchases.update_one(
        {"_id": purchase_id, "status": "creating_invoice"},
        {"$set": {"transaction_uuid": invoice.transaction_uuid, "status": "pending", "payment_url": invoice.url, "updated_at": to_utc_naive(utc_now())}},
    )
    return _custom_public(document, payment_url=invoice.url)


async def create_custom_cup_checkout(*, plugins: dict, billing_period: str, transfer_id: str) -> dict[str, Any]:
    cleaned = str(transfer_id or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="El ID de la transferencia es obligatorio.")
    selection, period, amount_usd, _discount = await quote_custom_selection(plugins, billing_period)
    rates = snapshot_cup_per_unit()
    usd_rate = rates.get("USD")
    if not usd_rate:
        raise HTTPException(status_code=503, detail="No hay tasa de cambio para mostrar el precio en CUP.")
    amount_cup = int((Decimal(str(amount_usd)) * Decimal(str(usd_rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    now = to_utc_naive(utc_now())
    purchase_id = ObjectId()
    document = {
        "_id": purchase_id,
        "remote_id": f"cup-plan-{purchase_id}",
        "seller_id": None,
        "store_name": "Nueva tienda",
        "purchase_kind": "custom",
        "plan_tier": "custom",
        "plan_plugins": selection,
        "billing_period": period,
        "plan_amount_usd": amount_usd,
        "invoice_amount_usd": amount_usd,
        "payment_amount_cup": amount_cup,
        "currency": "CUP",
        "payment_method": "cup",
        "transfer_id": cleaned,
        "exchange_rates_cup_per_unit": rates,
        "status": "submitted",
        "created_at": now,
        "updated_at": now,
    }
    await get_subscription_qvapay_purchases_collection().insert_one(document)
    return _custom_public(document)


async def create_plugin_addon_checkout(
    *,
    seller_id: str,
    plugins: dict,
    payment_method: str,
    transfer_id: str | None = None,
) -> dict[str, Any]:
    seller = await get_registrations_collection().find_one({"_id": _oid(seller_id, "Tienda no encontrada.")})
    if not seller or not is_subscription_active(seller):
        raise HTTPException(status_code=409, detail="Tu plan no está activo.")
    ends_at = seller.get("subscription_ends_at")
    if not isinstance(ends_at, datetime):
        raise HTTPException(status_code=409, detail="Tu plan no tiene una fecha de vencimiento.")
    period = normalize_billing_period(seller.get("billing_period"))
    selection, period, amount_usd, discount_percent = await quote_custom_selection(
        plugins,
        period,
        customers_included=seller_has_plugin(seller, "customers"),
    )
    rates = snapshot_cup_per_unit()
    usd_rate = rates.get("USD")
    amount_cup = (
        int((Decimal(str(amount_usd)) * Decimal(str(usd_rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if usd_rate
        else None
    )
    now = to_utc_naive(utc_now())
    purchase_id = ObjectId()
    document = {
        "_id": purchase_id,
        "remote_id": f"subscription-plan-{purchase_id}",
        "seller_id": str(seller_id),
        "store_name": seller.get("store_name") or "",
        "purchase_kind": "addon",
        "plan_tier": seller.get("plan_tier") or "standard",
        "plan_plugins": selection,
        "billing_period": period,
        "plan_amount_usd": amount_usd,
        "discount_percent": discount_percent if payment_method == "qvapay" else 0,
        "invoice_amount_usd": _discounted_usd(amount_usd, discount_percent) if payment_method == "qvapay" else amount_usd,
        "payment_amount_cup": amount_cup,
        "currency": "USD" if payment_method == "qvapay" else "CUP",
        "payment_method": payment_method,
        "addon_expires_at": to_utc_naive(ends_at),
        "exchange_rates_cup_per_unit": rates,
        "status": "creating_invoice" if payment_method == "qvapay" else "submitted",
        "created_at": now,
        "updated_at": now,
    }
    if payment_method == "cup":
        cleaned = str(transfer_id or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="El ID de la transferencia es obligatorio.")
        document["transfer_id"] = cleaned
        document["status"] = "submitted"
        await get_subscription_qvapay_purchases_collection().insert_one(document)
        return _custom_public(document)
    if not qvapay_configured():
        raise HTTPException(status_code=503, detail="Los pagos QvaPay no están disponibles ahora.")
    purchases = get_subscription_qvapay_purchases_collection()
    await purchases.insert_one(document)
    try:
        invoice = await create_invoice(
            amount=document["invoice_amount_usd"],
            description="Complemento de plan",
            remote_id=document["remote_id"],
        )
    except Exception:
        await purchases.update_one(
            {"_id": purchase_id, "status": "creating_invoice"},
            {"$set": {"status": "failed", "updated_at": to_utc_naive(utc_now())}},
        )
        raise
    document.update({"transaction_uuid": invoice.transaction_uuid, "status": "pending", "payment_url": invoice.url})
    await purchases.update_one(
        {"_id": purchase_id},
        {"$set": {"transaction_uuid": invoice.transaction_uuid, "status": "pending", "payment_url": invoice.url, "updated_at": to_utc_naive(utc_now())}},
    )
    return _custom_public(document, payment_url=invoice.url)


def _upgrade_plugins(raw: Any) -> dict[str, int]:
    plugins: dict[str, int] = {}
    for key, value in (raw or {}).items():
        try:
            qty = int(value or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            plugins[str(key)] = qty
    return plugins


async def latest_plan_upgrades_by_seller(seller_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [str(seller_id) for seller_id in seller_ids if seller_id]
    if not ids:
        return {}
    rows = await get_subscription_qvapay_purchases_collection().aggregate([
        {
            "$match": {
                "seller_id": {"$in": ids},
                "purchase_kind": "addon",
                "status": {"$in": ["submitted", "pending", "processing", "creating_invoice"]},
            }
        },
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$seller_id", "doc": {"$first": "$$ROOT"}}},
    ]).to_list(length=len(ids))
    upgrades: dict[str, dict[str, Any]] = {}
    for row in rows:
        doc = row.get("doc") or {}
        seller_id = str(row.get("_id") or doc.get("seller_id") or "")
        if not seller_id:
            continue
        upgrades[seller_id] = {
            "purchase_id": str(doc.get("_id") or ""),
            "payment_method": doc.get("payment_method") or "qvapay",
            "status": str(doc.get("status") or ""),
            "plan_plugins": _upgrade_plugins(doc.get("plan_plugins")),
            "billing_period": doc.get("billing_period"),
            "transfer_id": str(doc.get("transfer_id") or ""),
        }
    return upgrades


async def list_pending_addon_transfers() -> list[dict[str, Any]]:
    docs = await get_subscription_qvapay_purchases_collection().find(
        {"purchase_kind": "addon", "payment_method": "cup", "status": "submitted"}
    ).sort("created_at", -1).to_list(length=50)
    return [_custom_public(doc) for doc in docs]


async def approve_plugin_addon_transfer(purchase_id: str) -> dict[str, Any]:
    collection = get_subscription_qvapay_purchases_collection()
    purchase = await collection.find_one({"_id": _oid(purchase_id, "Compra no encontrada.")})
    if not purchase or purchase.get("purchase_kind") != "addon" or purchase.get("payment_method") != "cup":
        raise HTTPException(status_code=404, detail="Compra no encontrada.")
    if purchase.get("status") == "paid":
        return _custom_public(purchase)
    now = to_utc_naive(utc_now())
    claimed = await collection.update_one(
        {"_id": purchase["_id"], "status": "submitted"},
        {"$set": {"status": "processing", "updated_at": now}},
    )
    if claimed.modified_count != 1:
        raise HTTPException(status_code=409, detail="Esa transferencia ya fue revisada.")
    await _activate_paid_purchase(purchase)
    updated = await collection.find_one({"_id": purchase["_id"]})
    return _custom_public(updated or purchase)


async def load_open_custom_purchase(purchase_id: str) -> dict[str, Any]:
    doc = await get_subscription_qvapay_purchases_collection().find_one(
        {"_id": _oid(purchase_id, "No encontramos esa compra."), "seller_id": None, "purchase_kind": "custom"}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="No encontramos esa compra.")
    if doc.get("payment_method") == "qvapay" and doc.get("status") != "paid":
        raise HTTPException(status_code=409, detail="Paga la factura QvaPay antes de continuar con tus datos.")
    if doc.get("payment_method") == "cup" and doc.get("status") != "submitted":
        raise HTTPException(status_code=409, detail="Confirma la transferencia antes de continuar.")
    return doc


async def get_public_initial_subscription_checkout(*, purchase_id: str) -> dict[str, Any]:
    doc = await get_subscription_qvapay_purchases_collection().find_one(
        {"_id": _oid(purchase_id, "Factura no encontrada."), "seller_id": None}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Factura no encontrada.")
    return _checkout_public(doc)


async def validate_initial_subscription_checkout(*, purchase_id: str, plan_tier: str, billing_period: str) -> None:
    doc = await get_subscription_qvapay_purchases_collection().find_one(
        {"_id": _oid(purchase_id, "Factura no encontrada."), "seller_id": None, "status": "paid"}
    )
    if not doc:
        raise HTTPException(status_code=409, detail="Paga el plan QvaPay antes de continuar con tus datos.")
    if doc.get("plan_tier") != normalize_plan_tier(plan_tier) or doc.get("billing_period") != normalize_billing_period(billing_period):
        raise HTTPException(status_code=400, detail="El plan pagado no coincide con el plan seleccionado.")


async def attach_paid_subscription_checkout(*, seller_id: str, purchase_id: str, store_name: str) -> None:
    collection = get_subscription_qvapay_purchases_collection()
    purchase_oid = _oid(purchase_id, "Factura no encontrada.")
    result = await collection.update_one(
        {"_id": purchase_oid, "seller_id": None, "status": "paid"},
        {"$set": {"seller_id": str(seller_id), "store_name": store_name, "status": "processing", "updated_at": to_utc_naive(utc_now())}},
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="El pago del plan aún no está confirmado.")
    purchase = await collection.find_one({"_id": purchase_oid})
    await _activate_paid_purchase(purchase)


async def get_subscription_plan_checkout(*, seller_id: str, purchase_id: str) -> dict[str, Any]:
    doc = await get_subscription_qvapay_purchases_collection().find_one(
        {"_id": _oid(purchase_id, "Factura no encontrada."), "seller_id": str(seller_id)}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Factura no encontrada.")
    return _checkout_public(doc)


async def mark_subscription_plan_invoice_paid(
    *, remote_id: str | None, transaction_uuid: str | None, status_value: str
) -> bool:
    if not remote_id or not remote_id.startswith("subscription-plan-"):
        return False
    purchase_id = remote_id.removeprefix("subscription-plan-")
    collection = get_subscription_qvapay_purchases_collection()
    purchase = await collection.find_one({"_id": _oid(purchase_id, "Factura no encontrada."), "remote_id": remote_id})
    if not purchase:
        return False

    if transaction_uuid and purchase.get("transaction_uuid") != transaction_uuid:
        return True
    webhook_status = status_value.strip().lower()
    if webhook_status in {"cancelled", "canceled", "expired", "failed"}:
        await collection.update_one(
            {"_id": purchase["_id"], "status": "pending"},
            {"$set": {"status": "cancelled", "updated_at": to_utc_naive(utc_now())}},
        )
        return True
    if webhook_status not in {"paid", "completed", "success"}:
        return True
    now = to_utc_naive(utc_now())
    if purchase.get("status") == "paid" and not purchase.get("seller_id"):
        return True
    if purchase.get("status") == "paid" and purchase.get("activated_at"):
        return True
    claimed = await collection.update_one(
        {"_id": purchase["_id"], "status": {"$in": ["pending", "paid"]}},
        {"$set": {"status": "processing", "processing_at": now, "updated_at": now}},
    )
    if claimed.modified_count != 1:
        return True

    if not purchase.get("seller_id"):
        await collection.update_one(
            {"_id": purchase["_id"], "status": "processing"},
            {"$set": {"status": "paid", "paid_at": now, "updated_at": now}},
        )
        return True
    return await _activate_paid_purchase(purchase)


async def _activate_paid_purchase(purchase: dict[str, Any]) -> bool:
    collection = get_subscription_qvapay_purchases_collection()
    now = to_utc_naive(utc_now())
    seller_oid = _oid(purchase["seller_id"], "Tienda no encontrada.")
    registrations = get_registrations_collection()
    seller = await registrations.find_one({"_id": seller_oid})
    if not seller or seller.get("status") not in {"approved", "expired"}:
        await collection.update_one(
            {"_id": purchase["_id"], "status": "processing"},
            {"$set": {"status": "failed", "updated_at": to_utc_naive(utc_now())}},
        )
        return True

    tier = normalize_plan_tier(purchase["plan_tier"])
    period = normalize_billing_period(purchase["billing_period"])
    current_end = seller.get("subscription_ends_at")
    current_end = to_utc_naive(current_end) if isinstance(current_end, datetime) else None
    has_active_paid_subscription = (
        not seller.get("is_trial")
        and current_end is not None
        and current_end > now
    )
    is_renewal = has_active_paid_subscription and normalize_plan_tier(seller.get("plan_tier")) == tier
    # A plan change preserves the already-paid time; the new period begins when it ends.
    starts_at = current_end if has_active_paid_subscription else now
    ends_at = subscription_period_end(starts_at, period)
    rates = purchase.get("exchange_rates_cup_per_unit") or {}
    usd_rate = rates.get("USD") or snapshot_cup_per_unit().get("USD")
    payment_amount_cup = (
        int(
            (Decimal(str(purchase["invoice_amount_usd"])) * Decimal(str(usd_rate))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if usd_rate
        else None
    )
    seller_updates: dict[str, Any] = {
        "status": "approved",
        "plan_tier": tier,
        "billing_period": period,
        "is_trial": False,
        "subscription_starts_at": starts_at,
        "subscription_ends_at": ends_at,
        "payment_amount_cup": payment_amount_cup,
        "approved_at": now,
        "rejection_reason": None,
        "updated_at": now,
        **expiry_notice_reset(),
    }
    if purchase.get("purchase_kind") == "addon":
        merged = dict(seller.get("plugin_addons") or {})
        for key, qty in (purchase.get("plan_plugins") or {}).items():
            merged[key] = int(merged.get(key) or 0) + int(qty)
        seller_updates = {
            "plugin_addons": merged,
            "plugin_addons_expires_at": purchase.get("addon_expires_at") or seller.get("subscription_ends_at"),
            "updated_at": now,
        }
    elif purchase.get("plan_plugins"):
        seller_updates["plan_tier"] = "custom"
        seller_updates["plan_plugins"] = purchase.get("plan_plugins")
    await registrations.update_one({"_id": seller_oid}, {"$set": seller_updates})
    if payment_amount_cup is not None:
        await record_subscription_payment(
            registration_id=str(seller_oid),
            amount_cup=payment_amount_cup,
            kind="renewal" if is_renewal else "approval",
            recorded_at=now,
            plan_tier=tier,
            billing_period=period,
            external_payment_id=f"qvapay-plan-{purchase['_id']}",
        )
    await collection.update_one(
        {"_id": purchase["_id"], "status": "processing"},
        {
            "$set": {
                "status": "paid",
                "paid_at": now,
                "subscription_starts_at": starts_at,
                "subscription_ends_at": ends_at,
                "payment_amount_cup": payment_amount_cup,
                "activated_at": now,
                "updated_at": now,
            }
        },
    )
    return True
