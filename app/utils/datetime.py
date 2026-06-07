from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc_naive(value: datetime) -> datetime:
    """MongoDB stores datetimes without tz; keep everything as UTC naive."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
