"""Tráfico anónimo del marketplace (home /comprar)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.database import get_marketplace_visits_collection
from app.schemas.marketplace_traffic import (
    AdminTrafficByLocation,
    AdminTrafficChart,
    AdminTrafficLocationItem,
    AdminTrafficPatterns,
    MarketplaceVisitRecordResult,
    MarketplaceVisitRequest,
    TrafficDataPoint,
    TrafficGranularity,
)
from app.schemas.seller_stats import PeriodComparison
from app.services.cuba_locations import MUNICIPALITIES_BY_PROVINCE, PROVINCE_NAMES
from app.services.cuba_time import (
    cuba_date_str,
    cuba_hour,
    cuba_hour_label,
    cuba_weekday,
    cuba_weekday_label,
)
from app.services.seller_stats import (
    build_period_comparison,
    resolve_comparison_window,
)
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.month_bounds import (
    compare_month,
    current_month_year,
    iter_months,
    month_bounds,
    months_between_inclusive,
)

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


async def ensure_marketplace_visit_indexes() -> None:
    collection = get_marketplace_visits_collection()
    await collection.create_index(
        [("session_id", 1), ("page", 1), ("cuba_date", 1)],
        unique=True,
        name="marketplace_visit_session_day",
    )
    await collection.create_index([("viewed_at", -1)])
    await collection.create_index([("province_id", 1), ("municipality_id", 1), ("viewed_at", -1)])


def _day_label(day: int, month: int) -> str:
    return f"{day} {SPANISH_MONTHS[month - 1]}"


def _month_label(year: int, month: int) -> str:
    return f"{SPANISH_MONTHS_FULL[month - 1].capitalize()} {year}"


def _validate_location(province_id: str, municipality_id: str) -> tuple[str, str]:
    province_name = PROVINCE_NAMES.get(province_id)
    if not province_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provincia no válida.",
        )
    municipality_name = MUNICIPALITIES_BY_PROVINCE.get(province_id, {}).get(municipality_id)
    if not municipality_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Municipio no válido para la provincia seleccionada.",
        )
    return province_name, municipality_name


async def record_marketplace_visit(payload: MarketplaceVisitRequest) -> MarketplaceVisitRecordResult:
    province_name, municipality_name = _validate_location(
        payload.province_id,
        payload.municipality_id,
    )
    now = to_utc_naive(utc_now())
    document = {
        "session_id": payload.session_id,
        "page": payload.page,
        "province_id": payload.province_id,
        "province_name": province_name,
        "municipality_id": payload.municipality_id,
        "municipality_name": municipality_name,
        "viewed_at": now,
        "cuba_date": cuba_date_str(now),
        "cuba_hour": cuba_hour(now),
        "cuba_weekday": cuba_weekday(now),
    }

    try:
        await get_marketplace_visits_collection().insert_one(document)
    except DuplicateKeyError:
        return MarketplaceVisitRecordResult(recorded=False, duplicate=True)

    return MarketplaceVisitRecordResult(recorded=True, duplicate=False)


async def _earliest_visit_month() -> tuple[int, int]:
    earliest = await get_marketplace_visits_collection().find_one(
        {},
        sort=[("viewed_at", 1)],
        projection={"viewed_at": 1},
    )
    if earliest and isinstance(earliest.get("viewed_at"), datetime):
        viewed_at = to_utc_naive(earliest["viewed_at"])
        return viewed_at.year, viewed_at.month
    return current_month_year()


async def _traffic_period() -> dict[str, int]:
    earliest_year, earliest_month = await _earliest_visit_month()
    current_year, current_month = current_month_year()
    if compare_month(earliest_year, earliest_month, current_year, current_month) > 0:
        earliest_year, earliest_month = current_year, current_month
    return {
        "earliest_year": earliest_year,
        "earliest_month": earliest_month,
        "current_year": current_year,
        "current_month": current_month,
        "months_available": months_between_inclusive(
            earliest_year,
            earliest_month,
            current_year,
            current_month,
        ),
    }


def _validate_month(period: dict[str, int], year: int, month: int) -> None:
    if compare_month(year, month, period["earliest_year"], period["earliest_month"]) < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay tráfico registrado antes de esa fecha.",
        )
    if compare_month(year, month, period["current_year"], period["current_month"]) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese mes aún no ha comenzado.",
        )


def _week_ranges_in_month(
    year: int,
    month: int,
    *,
    cap_at: datetime | None,
) -> list[tuple[str, str, datetime, datetime]]:
    month_start, month_end = month_bounds(year, month)
    ranges: list[tuple[str, str, datetime, datetime]] = []
    cursor = month_start
    week_index = 1

    while cursor < month_end:
        week_end = min(cursor + timedelta(days=7), month_end)
        if cap_at is not None and cursor >= cap_at:
            break
        effective_end = week_end
        if cap_at is not None and cap_at < week_end:
            effective_end = cap_at

        start_day = cursor.day
        end_day = (effective_end - timedelta(seconds=1)).day
        label = (
            _day_label(start_day, month)
            if start_day == end_day
            else f"{start_day}–{end_day} {SPANISH_MONTHS[month - 1]}"
        )
        key = f"{year:04d}-{month:02d}-w{week_index}"
        ranges.append((key, label, cursor, effective_end))
        cursor = week_end
        week_index += 1

    return ranges


def _daily_ranges_in_month(
    year: int,
    month: int,
    *,
    cap_at: datetime | None,
) -> list[tuple[str, str, datetime, datetime]]:
    month_start, month_end = month_bounds(year, month)
    ranges: list[tuple[str, str, datetime, datetime]] = []
    cursor = month_start

    while cursor < month_end:
        if cap_at is not None and cursor >= cap_at:
            break
        next_day = min(cursor + timedelta(days=1), month_end)
        key = cursor.strftime("%Y-%m-%d")
        label = _day_label(cursor.day, month)
        ranges.append((key, label, cursor, next_day))
        cursor = next_day

    return ranges


def _monthly_ranges(period: dict[str, int]) -> list[tuple[str, str, datetime, datetime]]:
    ranges: list[tuple[str, str, datetime, datetime]] = []
    for year, month in iter_months(
        period["earliest_year"],
        period["earliest_month"],
        period["current_year"],
        period["current_month"],
    ):
        start, end = month_bounds(year, month)
        key = f"{year:04d}-{month:02d}"
        label = _month_label(year, month)
        ranges.append((key, label, start, end))
    return ranges


def _resolve_chart_ranges(
    period: dict[str, int],
    granularity: TrafficGranularity,
    year: int | None,
    month: int | None,
) -> tuple[list[tuple[str, str, datetime, datetime]], datetime, datetime, int | None, int | None]:
    if granularity == "monthly":
        if period["months_available"] < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Necesitas al menos dos meses de tráfico para ver el gráfico mensual.",
            )
        ranges = _monthly_ranges(period)
        return ranges, ranges[0][2], ranges[-1][3], None, None

    if year is None or month is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica el mes para ver el tráfico diario o semanal.",
        )

    _validate_month(period, year, month)
    now = to_utc_naive(utc_now())
    is_current_month = year == period["current_year"] and month == period["current_month"]
    cap_at = None
    if is_current_month:
        cap_at = to_utc_naive(
            datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
        )

    if granularity == "daily":
        ranges = _daily_ranges_in_month(year, month, cap_at=cap_at)
    else:
        ranges = _week_ranges_in_month(year, month, cap_at=cap_at)

    range_start = ranges[0][2] if ranges else month_bounds(year, month)[0]
    range_end = ranges[-1][3] if ranges else month_bounds(year, month)[1]
    return ranges, range_start, range_end, year, month


def _bucket_visits(
    visits: list[dict[str, Any]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> dict[str, int]:
    buckets = {key: 0 for key, _, _, _ in ranges}
    for visit in visits:
        viewed_at = visit.get("viewed_at")
        if not isinstance(viewed_at, datetime):
            continue
        viewed_at = to_utc_naive(viewed_at)
        for key, _, start, end in ranges:
            if start <= viewed_at < end:
                buckets[key] += 1
                break
    return buckets


async def _count_visits_between(start: datetime, end: datetime) -> int:
    return await get_marketplace_visits_collection().count_documents(
        {"viewed_at": {"$gte": start, "$lt": end}}
    )


async def get_traffic_chart(
    *,
    granularity: TrafficGranularity,
    year: int | None = None,
    month: int | None = None,
) -> AdminTrafficChart:
    period = await _traffic_period()
    ranges, range_start, range_end, chart_year, chart_month = _resolve_chart_ranges(
        period,
        granularity,
        year,
        month,
    )

    visits = await get_marketplace_visits_collection().find(
        {"viewed_at": {"$gte": range_start, "$lt": range_end}},
        projection={"viewed_at": 1},
    ).to_list(length=None)

    buckets = _bucket_visits(visits, ranges)
    points = [
        TrafficDataPoint(key=key, label=label, count=buckets.get(key, 0))
        for key, label, _, _ in ranges
    ]
    total_visits = sum(point.count for point in points)

    window = resolve_comparison_window(granularity)
    current_total = float(await _count_visits_between(window.current_start, window.current_end))
    previous_total = float(await _count_visits_between(window.previous_start, window.previous_end))

    earliest = await get_marketplace_visits_collection().find_one(
        {},
        sort=[("viewed_at", 1)],
        projection={"viewed_at": 1},
    )
    first_at = None
    if earliest and isinstance(earliest.get("viewed_at"), datetime):
        first_at = to_utc_naive(earliest["viewed_at"])

    comparison_available = first_at is not None and first_at < window.previous_start
    comparison: PeriodComparison = build_period_comparison(
        current_total,
        previous_total,
        window,
        available=comparison_available,
    )

    return AdminTrafficChart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        months_available=period["months_available"],
        total_visits=total_visits,
        points=points,
        comparison=comparison,
    )


async def get_traffic_by_location(*, year: int, month: int) -> AdminTrafficByLocation:
    period = await _traffic_period()
    _validate_month(period, year, month)
    start, end = month_bounds(year, month)

    pipeline = [
        {"$match": {"viewed_at": {"$gte": start, "$lt": end}}},
        {
            "$facet": {
                "provinces": [
                    {
                        "$group": {
                            "_id": {
                                "province_id": "$province_id",
                                "province_name": "$province_name",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1, "_id.province_name": 1}},
                ],
                "municipalities": [
                    {
                        "$group": {
                            "_id": {
                                "province_id": "$province_id",
                                "province_name": "$province_name",
                                "municipality_id": "$municipality_id",
                                "municipality_name": "$municipality_name",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1, "_id.municipality_name": 1}},
                    {"$limit": 25},
                ],
                "total": [{"$count": "count"}],
            }
        },
    ]

    rows = await get_marketplace_visits_collection().aggregate(pipeline).to_list(length=1)
    facet = rows[0] if rows else {}
    total = int((facet.get("total") or [{"count": 0}])[0].get("count") or 0)

    provinces = [
        AdminTrafficLocationItem(
            province_id=row["_id"]["province_id"],
            province_name=row["_id"]["province_name"],
            count=int(row["count"]),
        )
        for row in facet.get("provinces") or []
    ]
    municipalities = [
        AdminTrafficLocationItem(
            province_id=row["_id"]["province_id"],
            province_name=row["_id"]["province_name"],
            municipality_id=row["_id"]["municipality_id"],
            municipality_name=row["_id"]["municipality_name"],
            count=int(row["count"]),
        )
        for row in facet.get("municipalities") or []
    ]

    return AdminTrafficByLocation(
        year=year,
        month=month,
        total_visits=total,
        provinces=provinces,
        municipalities=municipalities,
    )


async def get_traffic_patterns(*, year: int, month: int) -> AdminTrafficPatterns:
    period = await _traffic_period()
    _validate_month(period, year, month)
    start, end = month_bounds(year, month)

    pipeline = [
        {"$match": {"viewed_at": {"$gte": start, "$lt": end}}},
        {
            "$facet": {
                "by_hour": [
                    {"$group": {"_id": "$cuba_hour", "count": {"$sum": 1}}},
                ],
                "by_weekday": [
                    {"$group": {"_id": "$cuba_weekday", "count": {"$sum": 1}}},
                ],
                "total": [{"$count": "count"}],
            }
        },
    ]
    rows = await get_marketplace_visits_collection().aggregate(pipeline).to_list(length=1)
    facet = rows[0] if rows else {}
    total = int((facet.get("total") or [{"count": 0}])[0].get("count") or 0)

    hour_counts = {
        int(row["_id"]): int(row["count"])
        for row in facet.get("by_hour") or []
        if row.get("_id") is not None
    }
    weekday_counts = {
        int(row["_id"]): int(row["count"])
        for row in facet.get("by_weekday") or []
        if row.get("_id") is not None
    }

    by_hour = [
        TrafficDataPoint(
            key=str(hour),
            label=cuba_hour_label(hour),
            count=hour_counts.get(hour, 0),
        )
        for hour in range(24)
    ]
    by_weekday = [
        TrafficDataPoint(
            key=str(day),
            label=cuba_weekday_label(day),
            count=weekday_counts.get(day, 0),
        )
        for day in range(7)
    ]

    return AdminTrafficPatterns(
        year=year,
        month=month,
        total_visits=total,
        by_hour=by_hour,
        by_weekday=by_weekday,
    )


async def count_visits_in_month(year: int, month: int) -> int:
    start, end = month_bounds(year, month)
    return await _count_visits_between(start, end)
