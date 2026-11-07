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
from app.services.exchange_rates import snapshot_cup_per_unit
from app.admin.service import get_plan_prices
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
    if currency == "USD":
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
    await collection.create_index("remote_id", unique=True)
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
    await registrations.update_one(
        {"_id": seller_oid},
        {
            "$set": {
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
        },
    )
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
