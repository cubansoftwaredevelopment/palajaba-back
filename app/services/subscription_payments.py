"""Historial de pagos de suscripción (ingresos de la plataforma)."""

from __future__ import annotations

from typing import Any, Literal

from bson import ObjectId

from app.database import get_registrations_collection, get_subscription_payments_collection
from app.utils.datetime import to_utc_naive, utc_now

PaymentKind = Literal["approval", "renewal", "adjustment"]


async def ensure_subscription_payment_indexes() -> None:
    collection = get_subscription_payments_collection()
    await collection.create_index([("recorded_at", -1)])
    await collection.create_index([("registration_id", 1), ("recorded_at", -1)])
    await backfill_subscription_payments_from_registrations()


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

    await get_subscription_payments_collection().insert_one(
        {
            "registration_id": registration_id,
            "amount_cup": int(amount_cup),
            "kind": kind,
            "recorded_at": when,
            "plan_tier": plan_tier,
            "billing_period": billing_period,
            "created_at": now,
        }
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
        await collection.delete_one({"_id": latest["_id"]})
        return

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


def registration_id_str(doc: dict[str, Any]) -> str:
    value = doc.get("_id")
    if isinstance(value, ObjectId):
        return str(value)
    return str(value)
