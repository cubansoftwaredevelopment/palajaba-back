from datetime import UTC, date, datetime

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
