"""Rangos de tiempo y velas OHLC para las gráficas del admin."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status

from app.utils.datetime import to_utc_naive, utc_now

SPANISH_MONTHS = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

SPANISH_MONTHS_FULL = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def to_epoch_ms(value: datetime) -> int:
    naive = to_utc_naive(value) if value.tzinfo is not None else value
    return int(calendar.timegm(naive.timetuple()) * 1000)


def parse_inclusive_dates(start: date | None, end: date | None) -> tuple[datetime, datetime] | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica la fecha de inicio y la de fin.",
        )
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha final no puede ser anterior a la inicial.",
        )

    start_dt = datetime(start.year, start.month, start.day)
    end_dt = datetime(end.year, end.month, end.day) + timedelta(days=1)
    now = to_utc_naive(utc_now())
    tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
    if start_dt >= tomorrow:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese rango aún no ha comenzado.",
        )
    if end_dt > tomorrow:
        end_dt = tomorrow
    if start_dt >= end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rango no tiene días para mostrar.",
        )
    return start_dt, end_dt


def _day_label(day: int, month: int) -> str:
    return f"{day} {SPANISH_MONTHS[month - 1]}"


def _month_label(year: int, month: int) -> str:
    return f"{SPANISH_MONTHS_FULL[month - 1].capitalize()} {year}"


def ranges_between(
    start: datetime,
    end: datetime,
    granularity: str,
) -> list[tuple[str, str, datetime, datetime]]:
    ranges: list[tuple[str, str, datetime, datetime]] = []

    if granularity == "monthly":
        cursor = datetime(start.year, start.month, 1)
        if cursor < start:
            cursor = start
        while cursor < end:
            if cursor.month == 12:
                month_end = datetime(cursor.year + 1, 1, 1)
            else:
                month_end = datetime(cursor.year, cursor.month + 1, 1)
            nxt = min(month_end, end)
            key = f"{cursor.year:04d}-{cursor.month:02d}"
            if ranges and ranges[-1][0] == key:
                key = f"{key}-{cursor.day:02d}"
            ranges.append((key, _month_label(cursor.year, cursor.month), cursor, nxt))
            cursor = nxt
        return ranges

    if granularity == "weekly":
        cursor = start
        week_index = 1
        while cursor < end:
            nxt = min(cursor + timedelta(days=7), end)
            last = nxt - timedelta(seconds=1)
            label = (
                _day_label(cursor.day, cursor.month)
                if cursor.day == last.day and cursor.month == last.month
                else f"{cursor.day}–{last.day} {SPANISH_MONTHS[cursor.month - 1]}"
            )
            key = f"{cursor.strftime('%Y-%m-%d')}-w{week_index}"
            ranges.append((key, label, cursor, nxt))
            cursor = nxt
            week_index += 1
        return ranges

    cursor = start
    while cursor < end:
        nxt = min(cursor + timedelta(days=1), end)
        key = cursor.strftime("%Y-%m-%d")
        ranges.append((key, _day_label(cursor.day, cursor.month), cursor, nxt))
        cursor = nxt
    return ranges


def build_cumulative_candles(
    events: list[tuple[datetime, float]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> list[dict[str, float | int | str]]:
    ordered = sorted(events, key=lambda item: item[0])
    index = 0
    cumulative = 0.0
    points: list[dict[str, float | int | str]] = []

    for key, label, start, end in ranges:
        open_value = cumulative
        high = cumulative
        low = cumulative
        bucket = 0.0
        while index < len(ordered) and ordered[index][0] < start:
            index += 1
        while index < len(ordered) and ordered[index][0] < end:
            amount = float(ordered[index][1])
            cumulative += amount
            bucket += amount
            high = max(high, cumulative)
            low = min(low, cumulative)
            index += 1
        points.append(
            {
                "key": key,
                "label": label,
                "time": to_epoch_ms(start),
                "bucket": bucket,
                "open": open_value,
                "high": high,
                "low": low,
                "close": cumulative,
            }
        )
    return points


def build_level_candles(
    values_by_key: dict[str, float],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> list[dict[str, float | int | str]]:
    previous = 0.0
    points: list[dict[str, float | int | str]] = []
    for key, label, start, _end in ranges:
        close = float(values_by_key.get(key, 0.0))
        open_value = previous
        points.append(
            {
                "key": key,
                "label": label,
                "time": to_epoch_ms(start),
                "bucket": close,
                "open": open_value,
                "high": max(open_value, close),
                "low": min(open_value, close),
                "close": close,
            }
        )
        previous = close
    return points
