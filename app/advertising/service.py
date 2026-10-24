from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.advertising.schemas import AdvertisingCheckoutPublic
from app.constants import ADVERTISING_PLAN_CATALOG, QVAPAY_EXCHANGE_FEE_RATE
from app.database import (
    get_advertising_purchases_collection,
    get_finance_ledger_collection,
    get_registrations_collection,
)
from app.notifications.otp_manager import send_custom_sms
from app.payments.qvapay import create_invoice
from app.schemas.platform_settings import AdvertisingPlanPublic
from app.services.exchange_rates import snapshot_cup_per_unit
from app.services.platform_settings import get_advertising_prices, get_platform_settings
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.phone import can_send_sms, to_e164

logger = logging.getLogger(__name__)

LEDGER_SOURCE = "advertising"


def _usd(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def invoice_amounts(plan_amount_usd: float) -> tuple[float, float, float]:
    plan = _usd(plan_amount_usd)
    fee = _usd(Decimal(str(plan)) * Decimal(str(QVAPAY_EXCHANGE_FEE_RATE)))
    total = _usd(Decimal(str(plan)) + Decimal(str(fee)))
    return plan, fee, total


def catalog_by_id() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in ADVERTISING_PLAN_CATALOG}


async def list_public_advertising_plans() -> list[AdvertisingPlanPublic]:
    prices = await get_advertising_prices()
    plans: list[AdvertisingPlanPublic] = []
    for item in ADVERTISING_PLAN_CATALOG:
        plan_id = str(item["id"])
        plan, fee, total = invoice_amounts(prices.get_amount(plan_id))
        plans.append(
            AdvertisingPlanPublic(
                id=plan_id,
                name=str(item["name"]),
                eyebrow=str(item["eyebrow"]),
                features=list(item["features"]),
                recommended=bool(item["recommended"]),
                amount_usd=plan,
                exchange_fee_usd=fee,
                invoice_amount_usd=total,
            )
        )
    return plans


async def ensure_advertising_indexes() -> None:
    collection = get_advertising_purchases_collection()
    await collection.create_index("seller_id")
    await collection.create_index("qvapay_transaction_uuid", unique=True, sparse=True)
    await collection.create_index("created_at")


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compra no encontrada.") from exc


async def checkout_advertising_plan(*, seller_id: str, plan_id: str) -> AdvertisingCheckoutPublic:
    catalog = catalog_by_id()
    item = catalog.get(plan_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese plan de publicidad no existe.")

    prices = await get_advertising_prices()
    plan_amount, fee, total = invoice_amounts(prices.get_amount(plan_id))
    now = to_utc_naive(utc_now())
    seller = await get_registrations_collection().find_one({"_id": _oid(seller_id)})
    store_name = str((seller or {}).get("store_name") or "tienda")

    document = {
        "seller_id": seller_id,
        "store_name": store_name,
        "plan_id": plan_id,
        "plan_name": item["name"],
        "plan_eyebrow": item["eyebrow"],
        "plan_amount_usd": plan_amount,
        "exchange_fee_usd": fee,
        "invoice_amount_usd": total,
        "currency": "USD",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    result = await get_advertising_purchases_collection().insert_one(document)
    purchase_id = str(result.inserted_id)

    plan_label = f"{item['eyebrow']} {item['name']}"
    product_name = f"Publicidad {plan_label}"
    invoice = await create_invoice(
        amount=total,
        description=f"{product_name} ({store_name})",
        remote_id=purchase_id,
        products=[
            {
                "name": product_name,
                "price": total,
            }
        ],
    )
    await get_advertising_purchases_collection().update_one(
        {"_id": result.inserted_id},
        {
            "$set": {
                "qvapay_transaction_uuid": invoice.transaction_uuid,
                "payment_url": invoice.url,
                "updated_at": to_utc_naive(utc_now()),
            }
        },
    )
    return AdvertisingCheckoutPublic(
        purchase_id=purchase_id,
        plan_id=plan_id,
        plan_name=str(item["name"]),
        plan_amount_usd=plan_amount,
        exchange_fee_usd=fee,
        invoice_amount_usd=total,
        payment_url=invoice.url,
    )


async def _sync_ledger_income(purchase: dict[str, Any]) -> Any:
    ledger = get_finance_ledger_collection()
    source_id = str(purchase["_id"])
    now = to_utc_naive(utc_now())
    payload = {
        "kind": "income",
        "amount": float(purchase.get("invoice_amount_usd") or 0),
        "currency": "USD",
        "reason": f"Publicidad — {purchase.get('plan_eyebrow') or 'Plan'} {purchase.get('plan_name') or ''}".strip(),
        "at": now,
        "source": LEDGER_SOURCE,
        "source_id": source_id,
        "rates": snapshot_cup_per_unit(),
    }
    existing = await ledger.find_one({"source": LEDGER_SOURCE, "source_id": source_id})
    if existing is not None:
        await ledger.update_one({"_id": existing["_id"]}, {"$set": payload})
        return existing["_id"]
    payload["created_at"] = now
    result = await ledger.insert_one(payload)
    return result.inserted_id


async def _notify_admins_payment(purchase: dict[str, Any]) -> None:
    settings = await get_platform_settings()
    store = str(purchase.get("store_name") or "una tienda")
    plan = str(purchase.get("plan_name") or "publicidad")
    total = purchase.get("invoice_amount_usd")
    fee = purchase.get("exchange_fee_usd")
    plan_amount = purchase.get("plan_amount_usd")
    message = (
        f"Pa' La Jaba: {store} pagó publicidad {plan}. "
        f"Plan {plan_amount} USD + exchange {fee} USD = {total} USD."
    )
    sent: set[str] = set()
    for admin in settings.admins:
        phone = to_e164(admin.phone)
        if not can_send_sms(phone) or phone in sent:
            continue
        sent.add(phone)
        try:
            await send_custom_sms(phone_e164=phone, message=message)
        except Exception:
            logger.exception("No se pudo avisar por SMS el pago de publicidad a %s.", phone)
    if not sent:
        logger.info("Pago de publicidad %s sin SMS: ningún admin con teléfono +53.", purchase.get("_id"))


async def mark_advertising_paid(
    *,
    remote_id: str | None,
    transaction_uuid: str | None,
    status_value: str | None,
) -> bool:
    if str(status_value or "").strip().lower() != "paid":
        return False

    collection = get_advertising_purchases_collection()
    query: dict[str, Any] | None = None
    if remote_id and ObjectId.is_valid(remote_id):
        query = {"_id": ObjectId(remote_id)}
    elif transaction_uuid:
        query = {"qvapay_transaction_uuid": str(transaction_uuid)}
    if query is None:
        return False

    purchase = await collection.find_one(query)
    if purchase is None:
        return False
    if purchase.get("status") == "paid":
        return True

    now = to_utc_naive(utc_now())
    updates: dict[str, Any] = {
        "status": "paid",
        "paid_at": now,
        "updated_at": now,
    }
    if transaction_uuid and not purchase.get("qvapay_transaction_uuid"):
        updates["qvapay_transaction_uuid"] = str(transaction_uuid)

    paid = {**purchase, **updates}
    ledger_id = await _sync_ledger_income(paid)
    updates["ledger_id"] = ledger_id
    await collection.update_one({"_id": purchase["_id"]}, {"$set": updates})
    await _notify_admins_payment({**paid, "ledger_id": ledger_id})
    return True
