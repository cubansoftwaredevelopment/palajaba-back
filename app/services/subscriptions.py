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
        from app.services.registrations import mark_registration_expired_if_needed

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


def warning_notification_content(days_remaining: int) -> str:
    day_label = "día" if days_remaining == 1 else "días"
    return (
        f"Te quedan {days_remaining} {day_label} antes de que termine tu suscripción. "
        "Renueva a tiempo para que tu tienda siga visible para los clientes."
    )


def contact_reminder_content(days_remaining: int, *, store_name: str | None = None) -> str:
    day_label = "día" if days_remaining == 1 else "días"
    store = (store_name or "").strip() or "tu tienda"
    return (
        f"Pa' La Jaba: a {store} le quedan {days_remaining} {day_label} de suscripción. "
        "Renueva a tiempo para que tu tienda siga visible."
    )
