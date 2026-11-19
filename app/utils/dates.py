from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status

from app.utils.datetime import to_utc_naive


def parse_subscription_end(value: str | date | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_utc_naive(value)
    if isinstance(value, date):
        return to_utc_naive(
            datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=UTC)
        )
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d")
            return to_utc_naive(parsed.replace(hour=23, minute=59, second=59, tzinfo=UTC))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return to_utc_naive(parsed)
    return None


def created_at_bounds(start: date | None, end: date | None) -> dict | None:
    """Rango inclusivo de días civiles. Cada extremo es opcional."""
    if start is None and end is None:
        return None
    if start is not None and end is not None and end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha final no puede ser anterior a la inicial.",
        )
    bounds: dict = {}
    if start is not None:
        bounds["$gte"] = datetime(start.year, start.month, start.day)
    if end is not None:
        bounds["$lt"] = datetime(end.year, end.month, end.day) + timedelta(days=1)
    return bounds
