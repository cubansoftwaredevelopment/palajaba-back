from typing import Any, Literal

from app.utils.currency_conversion import convert_amount

PlanTier = Literal["standard", "pro", "premium"]
BillingPeriod = Literal["monthly", "quarterly", "yearly"]
BILLING_PERIODS: tuple[BillingPeriod, ...] = ("monthly", "quarterly", "yearly")

STANDARD_PLAN_TIER: PlanTier = "standard"
PRO_PLAN_TIER: PlanTier = "pro"
PREMIUM_PLAN_TIER: PlanTier = "premium"
PLAN_TIER_ORDER: tuple[PlanTier, ...] = (
    STANDARD_PLAN_TIER,
    PRO_PLAN_TIER,
    PREMIUM_PLAN_TIER,
)

STANDARD_GESTOR_LIMIT = 10
PRO_GESTOR_LIMIT = 25
PRO_RECOMMENDATION_MULTIPLIER = 2
PREMIUM_RECOMMENDATION_MULTIPLIER = 4

PLAN_DISPLAY_NAMES: dict[PlanTier, str] = {
    STANDARD_PLAN_TIER: "Básico",
    PRO_PLAN_TIER: "Pro",
    PREMIUM_PLAN_TIER: "Premium",
}

_PLAN_RANK: dict[PlanTier, int] = {
    STANDARD_PLAN_TIER: 0,
    PRO_PLAN_TIER: 1,
    PREMIUM_PLAN_TIER: 2,
}

STATISTICS_PLAN_REQUIRED_MESSAGE = (
    "Las estadísticas están disponibles en el plan Prueba y en los planes Pro y Premium."
)
STORE_BANNERS_PLAN_REQUIRED_MESSAGE = (
    "Los banners de tienda están disponibles en el plan Prueba y en los planes Pro y Premium."
)
CATALOG_THEME_PLAN_REQUIRED_MESSAGE = (
    "La personalización del catálogo está disponible en el plan Premium."
)


def normalize_plan_tier(value: str | None) -> PlanTier:
    if value == PRO_PLAN_TIER:
        return PRO_PLAN_TIER
    if value == PREMIUM_PLAN_TIER:
        return PREMIUM_PLAN_TIER
    return STANDARD_PLAN_TIER


def effective_plan_tier(doc: dict) -> PlanTier:
    return normalize_plan_tier(doc.get("plan_tier"))


def feature_plan_tier(doc: dict | None) -> PlanTier:
    """Plan cuyas prestaciones aplican: la prueba gratuita equivale a Pro."""
    payload = doc or {}
    tier = effective_plan_tier(payload)
    if tier in (PRO_PLAN_TIER, PREMIUM_PLAN_TIER):
        return tier
    if payload.get("is_trial"):
        return PRO_PLAN_TIER
    return STANDARD_PLAN_TIER


def plan_rank(plan_tier: str | None) -> int:
    return _PLAN_RANK[normalize_plan_tier(plan_tier)]


def plan_search_rank(doc: dict) -> int:
    """0 = Premium (primero), 1 = Pro, 2 = Básico."""
    return 2 - plan_rank(effective_plan_tier(doc))


def plan_display_name(plan_tier: str | None) -> str:
    return PLAN_DISPLAY_NAMES[normalize_plan_tier(plan_tier)]


def seller_plan_display_name(doc: dict | None) -> str:
    payload = doc or {}
    if payload.get("is_trial"):
        return "Prueba"
    return plan_display_name(payload.get("plan_tier"))


def max_gestores_for_plan(plan_tier: str | None) -> int | None:
    """Tope de gestores por plan. None = ilimitado (Premium)."""
    tier = normalize_plan_tier(plan_tier)
    if tier == PREMIUM_PLAN_TIER:
        return None
    if tier == PRO_PLAN_TIER:
        return PRO_GESTOR_LIMIT
    return STANDARD_GESTOR_LIMIT


def max_gestores_for_seller(doc: dict | None) -> int | None:
    return max_gestores_for_plan(feature_plan_tier(doc))


def seller_can_add_gestor(plan_tier: str | None, current_count: int) -> bool:
    limit = max_gestores_for_plan(plan_tier)
    if limit is None:
        return True
    try:
        count = int(current_count)
    except (TypeError, ValueError):
        count = 0
    return count < limit


def normalize_billing_period(value: str | None) -> BillingPeriod:
    if value == "yearly":
        return "yearly"
    if value == "quarterly":
        return "quarterly"
    return "monthly"


async def plan_price_cup(plan_tier: str, billing_period: str) -> int:
    from app.services.platform_settings import get_plan_prices

    prices = await get_plan_prices()
    configured = prices.get_price(
        normalize_plan_tier(plan_tier),
        normalize_billing_period(billing_period),
    )
    return int(convert_amount(configured.amount, configured.currency, "CUP"))


def seller_has_statistics(doc: dict) -> bool:
    return plan_rank(feature_plan_tier(doc)) >= 1


def seller_has_recommendation_boost(doc: dict) -> bool:
    return seller_has_statistics(doc)


def seller_has_store_banners(doc: dict) -> bool:
    return plan_rank(feature_plan_tier(doc)) >= 1


def seller_has_full_store_customization(doc: dict) -> bool:
    return feature_plan_tier(doc) == PREMIUM_PLAN_TIER


def seller_has_product_discounts(doc: dict) -> bool:
    return plan_rank(feature_plan_tier(doc)) >= 1


def recommendation_multiplier(doc: dict) -> int:
    tier = feature_plan_tier(doc)
    if tier == PREMIUM_PLAN_TIER:
        return PREMIUM_RECOMMENDATION_MULTIPLIER
    if tier == PRO_PLAN_TIER:
        return PRO_RECOMMENDATION_MULTIPLIER
    return 1


from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.database import get_registrations_collection
from app.utils.datetime import to_utc_naive, utc_now

SUBSCRIPTION_WARNING_DAYS = 3
SUBSCRIPTION_CONTACT_REMINDER_DAYS = 2
SUBSCRIPTION_URGENT_BANNER_HOURS = 24
NOTIFICATION_KIND_EXPIRING = "subscription_expiring"
ACTION_RENEW_SUBSCRIPTION = "renew_subscription"
EXPIRY_NOTICE_SMS_FIELD = "subscription_expiry_notice_sms_sent"
EXPIRY_NOTICE_FOR_FIELD = "subscription_expiry_notice_for"


def expiry_notice_reset() -> dict[str, Any]:
    return {
        EXPIRY_NOTICE_FOR_FIELD: None,
        EXPIRY_NOTICE_SMS_FIELD: False,
        "subscription_expiry_notice_sms": None,
    }


def _same_subscription_end(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    return to_utc_naive(left) == to_utc_naive(right)


def expiry_notice_channel_state(doc: dict[str, Any], channel: str, ends_at: datetime | None) -> str | None:
    if not _same_subscription_end(doc.get(EXPIRY_NOTICE_FOR_FIELD), ends_at):
        return None
    value = doc.get(f"subscription_expiry_notice_{channel}")
    if value in ("sent", "skipped", "retry"):
        return value
    if channel == "sms" and doc.get(EXPIRY_NOTICE_SMS_FIELD) is True:
        return "sent"
    return None


def expiry_notice_sent(doc: dict[str, Any], channel: str, ends_at: datetime | None) -> bool:
    return expiry_notice_channel_state(doc, channel, ends_at) == "sent"


def normalize_subscription_end(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def subscription_days_remaining(
    doc: dict[str, Any],
    *,
    now: datetime | None = None,
) -> int | None:
    ends_at = normalize_subscription_end(doc.get("subscription_ends_at"))
    if ends_at is None:
        return None

    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    else:
        reference = reference.astimezone(UTC)

    if ends_at <= reference:
        return 0

    remaining = ends_at - reference
    return max(0, remaining.days)


def subscription_hours_remaining(
    doc: dict[str, Any],
    *,
    now: datetime | None = None,
) -> int | None:
    ends_at = normalize_subscription_end(doc.get("subscription_ends_at"))
    if ends_at is None:
        return None

    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    else:
        reference = reference.astimezone(UTC)

    if ends_at <= reference:
        return 0

    remaining = ends_at - reference
    return max(0, int(remaining.total_seconds() // 3600))


def is_within_urgent_banner_window(
    doc: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    hours = subscription_hours_remaining(doc, now=now)
    return hours is not None and 0 < hours <= SUBSCRIPTION_URGENT_BANNER_HOURS


def is_subscription_active(
    doc: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    if doc.get("status") != "approved":
        return False

    ends_at = normalize_subscription_end(doc.get("subscription_ends_at"))
    if ends_at is None:
        return True

    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    else:
        reference = reference.astimezone(UTC)

    return ends_at > reference


def is_publicly_visible(doc: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Tiendas expiradas no deben aparecer en la vista pública."""
    return is_subscription_active(doc, now=now)


def subscription_expired_detail(doc: dict[str, Any]) -> dict[str, Any]:
    ends_at = doc.get("subscription_ends_at")
    return {
        "code": "subscription_expired",
        "message": (
            "Tu suscripción ha expirado. Renueva tu plan para volver a "
            "activar tu tienda."
        ),
        "store_name": doc.get("store_name"),
        "subscription_ends_at": ends_at.isoformat() if isinstance(ends_at, datetime) else None,
    }


def raise_subscription_expired(doc: dict[str, Any]) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=subscription_expired_detail(doc),
    )


async def assert_seller_subscription_active(seller_id: str) -> dict[str, Any]:
    try:
        seller_object_id = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    collection = get_registrations_collection()
    doc = await collection.find_one({"_id": seller_object_id})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not is_subscription_active(doc):
        from app.services.platform_settings import get_renewal_contact_phone
        from app.auth.registrations import mark_registration_expired_if_needed

        await mark_registration_expired_if_needed(doc)
        detail = subscription_expired_detail(doc)
        detail["renewal_contact_phone"] = await get_renewal_contact_phone()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )

    return doc


def is_within_warning_window(doc: dict[str, Any], *, now: datetime | None = None) -> bool:
    days = subscription_days_remaining(doc, now=now)
    return days is not None and 0 < days <= SUBSCRIPTION_WARNING_DAYS


def is_within_contact_reminder_window(doc: dict[str, Any], *, now: datetime | None = None) -> bool:
    days = subscription_days_remaining(doc, now=now)
    return days is not None and 0 < days <= SUBSCRIPTION_CONTACT_REMINDER_DAYS


def expiry_notice_title(*, is_trial: bool = False) -> str:
    return "Tu plan Prueba vence pronto" if is_trial else "Tu suscripción vence pronto"


def warning_notification_content(days_remaining: int, *, is_trial: bool = False) -> str:
    day_label = "día" if days_remaining == 1 else "días"
    if is_trial:
        return (
            f"Te quedan {days_remaining} {day_label} del plan Prueba. "
            "Pasa a Básico, Pro o Premium para que tu tienda siga visible para los clientes."
        )
    return (
        f"Te quedan {days_remaining} {day_label} antes de que termine tu suscripción. "
        "Renueva a tiempo para que tu tienda siga visible para los clientes."
    )


def contact_reminder_content(
    days_remaining: int,
    *,
    store_name: str | None = None,
    is_trial: bool = False,
) -> str:
    day_label = "día" if days_remaining == 1 else "días"
    store = (store_name or "").strip() or "tu tienda"
    if is_trial:
        return (
            f"Pa' La Jaba: a {store} le quedan {days_remaining} {day_label} del plan Prueba. "
            "Pasa a Básico, Pro o Premium para que tu tienda siga visible."
        )
    return (
        f"Pa' La Jaba: a {store} le quedan {days_remaining} {day_label} de suscripción. "
        "Renueva a tiempo para que tu tienda siga visible."
    )


"""Historial de pagos de suscripción (ingresos de la plataforma)."""

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
