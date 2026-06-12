from datetime import UTC, datetime

from app.utils.datetime import to_utc_naive, utc_now


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return to_utc_naive(start), to_utc_naive(end)


def current_month_year() -> tuple[int, int]:
    now = utc_now()
    return now.year, now.month


def months_between_inclusive(start_year: int, start_month: int, end_year: int, end_month: int) -> int:
    return (end_year - start_year) * 12 + (end_month - start_month) + 1


def iter_months(start_year: int, start_month: int, end_year: int, end_month: int):
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        yield year, month
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def compare_month(year: int, month: int, other_year: int, other_month: int) -> int:
    if year != other_year:
        return -1 if year < other_year else 1
    if month != other_month:
        return -1 if month < other_month else 1
    return 0
