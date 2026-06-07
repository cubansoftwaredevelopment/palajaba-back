from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated

from pydantic import PlainSerializer

# Cuba (UTC-4, sin horario de verano desde 2015) — facturas PDF y textos del servidor
APP_DISPLAY_TZ = timezone(timedelta(hours=-4))


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc_naive(value: datetime) -> datetime:
    """MongoDB stores datetimes without tz; keep everything as UTC naive."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def serialize_utc_datetime(value: datetime) -> str:
    """ISO 8601 con sufijo Z para que el cliente convierta a su zona horaria."""
    aware = as_utc_aware(value).replace(microsecond=0)
    return aware.isoformat().replace("+00:00", "Z")


def format_utc_naive_for_display(
    value: datetime | None,
    tz: timezone = APP_DISPLAY_TZ,
) -> str:
    if value is None:
        return "—"
    local = as_utc_aware(value).astimezone(tz)
    return local.strftime("%d/%m/%Y %H:%M")


UtcDateTime = Annotated[
    datetime,
    PlainSerializer(serialize_utc_datetime, when_used="json-unless-none"),
]
