from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.database import get_registrations_collection
from app.utils.datetime import to_utc_naive, utc_now

SUBSCRIPTION_WARNING_DAYS = 3
SUBSCRIPTION_URGENT_BANNER_HOURS = 24
NOTIFICATION_KIND_EXPIRING = "subscription_expiring"
ACTION_RENEW_SUBSCRIPTION = "renew_subscription"


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
        raise_subscription_expired(doc)

    return doc


def is_within_warning_window(doc: dict[str, Any], *, now: datetime | None = None) -> bool:
    days = subscription_days_remaining(doc, now=now)
    return days is not None and 0 < days <= SUBSCRIPTION_WARNING_DAYS


def warning_notification_content(days_remaining: int) -> str:
    day_label = "día" if days_remaining == 1 else "días"
    return (
        f"Te quedan {days_remaining} {day_label} antes de que termine tu suscripción. "
        "Renueva a tiempo para que tu tienda siga visible para los clientes."
    )
