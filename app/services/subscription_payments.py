"""Historial de pagos de suscripción (ingresos de la plataforma)."""

from __future__ import annotations

from typing import Any, Literal

from bson import ObjectId

from app.database import (
    get_finance_ledger_collection,
    get_registrations_collection,
    get_subscription_payments_collection,
)
from app.services.exchange_rates import snapshot_cup_per_unit
from app.utils.datetime import to_utc_naive, utc_now

PaymentKind = Literal["approval", "renewal", "adjustment"]

LEDGER_REASONS = {
    "approval": "Alta de plan",
    "renewal": "Renovación",
    "adjustment": "Ajuste",
}


async def _sync_ledger_income(
    *,
    payment_id: Any,
    amount_cup: int,
    kind: PaymentKind,
    at,
    rates: dict[str, float],
) -> Any:
    ledger = get_finance_ledger_collection()
    source_id = str(payment_id)
    payload = {
        "kind": "income",
        "amount": float(amount_cup),
        "currency": "CUP",
        "reason": LEDGER_REASONS.get(kind, "Alta de plan"),
        "at": at,
        "source": "subscription",
        "source_id": source_id,
        "rates": rates,
    }
    existing = await ledger.find_one({"source": "subscription", "source_id": source_id})
    if existing is not None:
        await ledger.update_one({"_id": existing["_id"]}, {"$set": payload})
        return existing["_id"]
    payload["created_at"] = to_utc_naive(utc_now())
    result = await ledger.insert_one(payload)
    return result.inserted_id


async def _delete_ledger_income(payment_id: Any) -> None:
    await get_finance_ledger_collection().delete_one(
        {"source": "subscription", "source_id": str(payment_id)}
    )


async def ensure_subscription_payment_indexes() -> None:
    collection = get_subscription_payments_collection()
    await collection.create_index([("recorded_at", -1)])
    await collection.create_index([("registration_id", 1), ("recorded_at", -1)])
    await backfill_subscription_payments_from_registrations()
    await backfill_finance_ledger_from_payments()


async def record_subscription_payment(
    *,
    registration_id: str,
    amount_cup: int,
    kind: PaymentKind,
    recorded_at=None,
    plan_tier: str | None = None,
    billing_period: str | None = None,
) -> None:
    if amount_cup <= 0:
        return

    now = to_utc_naive(utc_now())
    when = to_utc_naive(recorded_at) if recorded_at is not None else now
    rates = snapshot_cup_per_unit()
    document = {
        "registration_id": registration_id,
        "amount_cup": int(amount_cup),
        "kind": kind,
        "recorded_at": when,
        "plan_tier": plan_tier,
        "billing_period": billing_period,
        "created_at": now,
        "rates": rates,
    }
    result = await get_subscription_payments_collection().insert_one(document)
    ledger_id = await _sync_ledger_income(
        payment_id=result.inserted_id,
        amount_cup=amount_cup,
        kind=kind,
        at=when,
        rates=rates,
    )
    await get_subscription_payments_collection().update_one(
        {"_id": result.inserted_id},
        {"$set": {"ledger_id": ledger_id}},
    )


async def upsert_latest_subscription_payment(
    *,
    registration_id: str,
    amount_cup: int,
    fallback_recorded_at=None,
    plan_tier: str | None = None,
    billing_period: str | None = None,
) -> None:
    """Actualiza el último pago del registro, o lo crea si no existe."""
    collection = get_subscription_payments_collection()
    latest = await collection.find_one(
        {"registration_id": registration_id},
        sort=[("recorded_at", -1)],
    )
    now = to_utc_naive(utc_now())

    if latest is None:
        if amount_cup <= 0:
            return
        await record_subscription_payment(
            registration_id=registration_id,
            amount_cup=amount_cup,
            kind="adjustment",
            recorded_at=fallback_recorded_at or now,
            plan_tier=plan_tier,
            billing_period=billing_period,
        )
        return

    if amount_cup <= 0:
        await _delete_ledger_income(latest["_id"])
        await collection.delete_one({"_id": latest["_id"]})
        return

    rates = latest.get("rates") if isinstance(latest.get("rates"), dict) and latest.get("rates") else snapshot_cup_per_unit()
    ledger_id = await _sync_ledger_income(
        payment_id=latest["_id"],
        amount_cup=amount_cup,
        kind="adjustment",
        at=latest.get("recorded_at") or now,
        rates=rates,
    )
    await collection.update_one(
        {"_id": latest["_id"]},
        {
            "$set": {
                "amount_cup": int(amount_cup),
                "kind": "adjustment",
                "plan_tier": plan_tier if plan_tier is not None else latest.get("plan_tier"),
                "billing_period": (
                    billing_period if billing_period is not None else latest.get("billing_period")
                ),
                "updated_at": now,
                "ledger_id": ledger_id,
                "rates": rates,
            }
        },
    )


async def backfill_subscription_payments_from_registrations() -> int:
    """Crea un pago histórico por cada tienda aprobada/renovada sin ledger."""
    payments = get_subscription_payments_collection()
    registrations = get_registrations_collection()

    existing_ids: set[str] = set()
    async for row in payments.find({}, projection={"registration_id": 1}):
        registration_id = row.get("registration_id")
        if registration_id:
            existing_ids.add(str(registration_id))

    cursor = registrations.find(
        {
            "status": {"$in": ["approved", "expired"]},
            "payment_amount_cup": {"$gt": 0},
            "approved_at": {"$exists": True, "$ne": None},
        },
        projection={
            "_id": 1,
            "payment_amount_cup": 1,
            "approved_at": 1,
            "plan_tier": 1,
            "billing_period": 1,
        },
    )

    inserted = 0
    async for doc in cursor:
        registration_id = str(doc["_id"])
        if registration_id in existing_ids:
            continue

        amount = int(doc.get("payment_amount_cup") or 0)
        recorded_at = doc.get("approved_at")
        if amount <= 0 or recorded_at is None:
            continue

        await record_subscription_payment(
            registration_id=registration_id,
            amount_cup=amount,
            kind="approval",
            recorded_at=recorded_at,
            plan_tier=doc.get("plan_tier"),
            billing_period=doc.get("billing_period"),
        )
        inserted += 1

    return inserted


async def backfill_finance_ledger_from_payments() -> int:
    payments = get_subscription_payments_collection()
    inserted = 0
    async for pay in payments.find({"amount_cup": {"$gt": 0}}):
        rates = pay.get("rates") if isinstance(pay.get("rates"), dict) and pay.get("rates") else snapshot_cup_per_unit()
        ledger_id = await _sync_ledger_income(
            payment_id=pay["_id"],
            amount_cup=int(pay.get("amount_cup") or 0),
            kind=pay.get("kind") or "approval",
            at=pay.get("recorded_at") or pay.get("created_at") or to_utc_naive(utc_now()),
            rates=rates,
        )
        if pay.get("ledger_id") != ledger_id:
            await payments.update_one({"_id": pay["_id"]}, {"$set": {"ledger_id": ledger_id, "rates": rates}})
            inserted += 1
    return inserted


def registration_id_str(doc: dict[str, Any]) -> str:
    value = doc.get("_id")
    if isinstance(value, ObjectId):
        return str(value)
    return str(value)
