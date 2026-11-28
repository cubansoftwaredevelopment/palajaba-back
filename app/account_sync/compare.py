"""Compara la fecha de una sección del teléfono con la del servidor."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.utils.datetime import serialize_utc_datetime, to_utc_naive, utc_now

FUTURE_SKEW = timedelta(minutes=5)


def parse_phone_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_utc_naive(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return to_utc_naive(parsed)


def _second(value: datetime) -> datetime:
    return value.replace(microsecond=0)


def section_verdict(phone_raw: Any, server_at: datetime | None, *, now: datetime | None = None) -> bool | None:
    """True si el teléfono es más reciente, False si es más antiguo, None si son iguales.

    Sin fecha en ningún lado no hay nada que bajar ni que subir.
    Una fecha del teléfono más de unos minutos en el futuro se trata como anterior.
    """
    now_at = _second(to_utc_naive(now or utc_now()))
    phone_at = parse_phone_date(phone_raw)
    server = _second(server_at) if isinstance(server_at, datetime) else None
    if phone_at is None and server is None:
        return None
    if phone_at is None:
        return False
    phone = _second(phone_at)
    if phone > now_at + FUTURE_SKEW:
        return False
    if server is None:
        return True
    if phone > server:
        return True
    if phone < server:
        return False
    return None


def verdicts_for(server_dates: dict[str, datetime | None], phone_dates: dict[str, Any]) -> dict[str, bool | None]:
    return {name: section_verdict(phone_dates.get(name), server_at) for name, server_at in server_dates.items()}


def as_iso(value: datetime | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    return serialize_utc_datetime(to_utc_naive(value))


def newest(*values: datetime | None) -> datetime | None:
    found = [value for value in values if isinstance(value, datetime)]
    if not found:
        return None
    return max(to_utc_naive(value) for value in found)


def section_clock(doc: dict[str, Any] | None, name: str) -> datetime | None:
    if not doc:
        return None
    raw = (doc.get("section_updated_at") or {}).get(name)
    if isinstance(raw, datetime):
        return to_utc_naive(raw)
    return None
