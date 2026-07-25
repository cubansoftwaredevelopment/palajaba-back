"""Estadísticas admin de pedidos completados (volumen, top negocios, geo)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.database import get_orders_collection, get_registrations_collection
from app.schemas.admin_order_stats import (
    AdminOrdersByLocation,
    AdminOrdersChart,
    AdminOrdersLocationItem,
    AdminTopBusinesses,
    AdminTopBusinessItem,
    OrdersGranularity,
)
from app.schemas.marketplace_traffic import TrafficDataPoint
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

TOP_BUSINESSES_LIMIT = 10


def _day_label(day: int, month: int) -> str:
    return f"{day} {SPANISH_MONTHS[month - 1]}"


def _month_label(year: int, month: int) -> str:
    return f"{SPANISH_MONTHS_FULL[month - 1].capitalize()} {year}"


async def _earliest_completed_month() -> tuple[int, int]:
    earliest = await get_orders_collection().find_one(
        {"status": "completed", "completed_at": {"$ne": None}},
        sort=[("completed_at", 1)],
        projection={"completed_at": 1},
    )
    if earliest and isinstance(earliest.get("completed_at"), datetime):
        completed_at = to_utc_naive(earliest["completed_at"])
        return completed_at.year, completed_at.month
    return current_month_year()


async def _orders_period() -> dict[str, int]:
    earliest_year, earliest_month = await _earliest_completed_month()
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
            detail="No hay pedidos completados antes de esa fecha.",
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
    granularity: OrdersGranularity,
    year: int | None,
    month: int | None,
) -> tuple[list[tuple[str, str, datetime, datetime]], datetime, datetime, int | None, int | None]:
    if granularity == "monthly":
        if period["months_available"] < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Necesitas al menos dos meses de pedidos para ver el gráfico mensual.",
            )
        ranges = _monthly_ranges(period)
        return ranges, ranges[0][2], ranges[-1][3], None, None

    if year is None or month is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica el mes para ver los pedidos diarios o semanales.",
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


def _bucket_orders(
    orders: list[dict[str, Any]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> dict[str, int]:
    buckets = {key: 0 for key, _, _, _ in ranges}
    for order in orders:
        completed_at = order.get("completed_at")
        if not isinstance(completed_at, datetime):
            continue
        completed_at = to_utc_naive(completed_at)
        for key, _, start, end in ranges:
            if start <= completed_at < end:
                buckets[key] += 1
                break
    return buckets


async def _count_completed_between(start: datetime, end: datetime) -> int:
    return await get_orders_collection().count_documents(
        {
            "status": "completed",
            "completed_at": {"$gte": start, "$lt": end},
        }
    )


def _period_window_for_granularity(
    granularity: OrdersGranularity,
) -> tuple[datetime, datetime, str, int | None, int | None]:
    window = resolve_comparison_window(granularity)
    year = window.current_start.year
    month = window.current_start.month
    return (
        window.current_start,
        window.current_end,
        window.period_label,
        year,
        month,
    )


async def get_orders_chart(
    *,
    granularity: OrdersGranularity,
    year: int | None = None,
    month: int | None = None,
) -> AdminOrdersChart:
    period = await _orders_period()
    ranges, range_start, range_end, chart_year, chart_month = _resolve_chart_ranges(
        period,
        granularity,
        year,
        month,
    )

    orders = await get_orders_collection().find(
        {
            "status": "completed",
            "completed_at": {"$gte": range_start, "$lt": range_end},
        },
        projection={"completed_at": 1},
    ).to_list(length=None)

    buckets = _bucket_orders(orders, ranges)
    points = [
        TrafficDataPoint(key=key, label=label, count=buckets.get(key, 0))
        for key, label, _, _ in ranges
    ]
    total_orders = sum(point.count for point in points)

    window = resolve_comparison_window(granularity)
    current_total = float(
        await _count_completed_between(window.current_start, window.current_end)
    )
    previous_total = float(
        await _count_completed_between(window.previous_start, window.previous_end)
    )

    earliest = await get_orders_collection().find_one(
        {"status": "completed", "completed_at": {"$ne": None}},
        sort=[("completed_at", 1)],
        projection={"completed_at": 1},
    )
    first_at = None
    if earliest and isinstance(earliest.get("completed_at"), datetime):
        first_at = to_utc_naive(earliest["completed_at"])

    comparison = build_period_comparison(
        current_total,
        previous_total,
        window,
        available=first_at is not None and first_at < window.previous_start,
    )

    return AdminOrdersChart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        months_available=period["months_available"],
        total_orders=total_orders,
        points=points,
        comparison=comparison,
    )


async def get_top_businesses(
    *,
    granularity: OrdersGranularity,
) -> AdminTopBusinesses:
    start, end, period_label, year, month = _period_window_for_granularity(granularity)

    pipeline = [
        {
            "$match": {
                "status": "completed",
                "completed_at": {"$gte": start, "$lt": end},
            }
        },
        {
            "$group": {
                "_id": "$seller_id",
                "store_name": {"$first": "$store_name"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1, "store_name": 1}},
        {"$limit": TOP_BUSINESSES_LIMIT},
    ]
    rows = await get_orders_collection().aggregate(pipeline).to_list(length=None)
    total_orders = await _count_completed_between(start, end)

    seller_ids: list[ObjectId] = []
    for row in rows:
        try:
            seller_ids.append(ObjectId(str(row["_id"])))
        except (InvalidId, TypeError):
            continue

    sellers_by_id: dict[str, dict[str, Any]] = {}
    if seller_ids:
        async for seller in get_registrations_collection().find(
            {"_id": {"$in": seller_ids}},
            projection={
                "store_name": 1,
                "store_slug": 1,
                "business_area": 1,
            },
        ):
            sellers_by_id[str(seller["_id"])] = seller

    businesses: list[AdminTopBusinessItem] = []
    for row in rows:
        seller_id = str(row["_id"])
        seller = sellers_by_id.get(seller_id, {})
        area = seller.get("business_area") or {}
        businesses.append(
            AdminTopBusinessItem(
                seller_id=seller_id,
                store_name=(seller.get("store_name") or row.get("store_name") or "Tienda").strip(),
                store_slug=seller.get("store_slug"),
                count=int(row["count"]),
                province_name=area.get("province_name"),
                municipality_name=area.get("municipality_name"),
            )
        )

    return AdminTopBusinesses(
        granularity=granularity,
        year=year,
        month=month,
        period_label=period_label,
        total_orders=total_orders,
        businesses=businesses,
    )


async def get_orders_by_location(
    *,
    granularity: OrdersGranularity,
) -> AdminOrdersByLocation:
    start, end, period_label, year, month = _period_window_for_granularity(granularity)

    pipeline = [
        {
            "$match": {
                "status": "completed",
                "completed_at": {"$gte": start, "$lt": end},
            }
        },
        {
            "$addFields": {
                "seller_oid": {
                    "$convert": {
                        "input": "$seller_id",
                        "to": "objectId",
                        "onError": None,
                        "onNull": None,
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "registrations",
                "localField": "seller_oid",
                "foreignField": "_id",
                "as": "seller",
            }
        },
        {"$unwind": {"path": "$seller", "preserveNullAndEmptyArrays": True}},
        {
            "$facet": {
                "provinces": [
                    {
                        "$match": {
                            "seller.business_area.province_id": {
                                "$exists": True,
                                "$nin": [None, ""],
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "province_id": "$seller.business_area.province_id",
                                "province_name": "$seller.business_area.province_name",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1, "_id.province_name": 1}},
                ],
                "municipalities": [
                    {
                        "$match": {
                            "seller.business_area.municipality_id": {
                                "$exists": True,
                                "$nin": [None, ""],
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "province_id": "$seller.business_area.province_id",
                                "province_name": "$seller.business_area.province_name",
                                "municipality_id": "$seller.business_area.municipality_id",
                                "municipality_name": "$seller.business_area.municipality_name",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1, "_id.municipality_name": 1}},
                    {"$limit": 25},
                ],
                "without_location": [
                    {
                        "$match": {
                            "$or": [
                                {"seller": {"$eq": None}},
                                {"seller.business_area": {"$exists": False}},
                                {"seller.business_area.province_id": {"$in": [None, ""]}},
                            ]
                        }
                    },
                    {"$count": "count"},
                ],
                "total": [{"$count": "count"}],
            }
        },
    ]

    rows = await get_orders_collection().aggregate(pipeline).to_list(length=1)
    facet = rows[0] if rows else {}
    total = int((facet.get("total") or [{"count": 0}])[0].get("count") or 0)
    without_location = int(
        (facet.get("without_location") or [{"count": 0}])[0].get("count") or 0
    )

    provinces = [
        AdminOrdersLocationItem(
            province_id=row["_id"]["province_id"],
            province_name=row["_id"].get("province_name") or row["_id"]["province_id"],
            count=int(row["count"]),
        )
        for row in facet.get("provinces") or []
        if row.get("_id") and row["_id"].get("province_id")
    ]
    municipalities = [
        AdminOrdersLocationItem(
            province_id=row["_id"]["province_id"],
            province_name=row["_id"].get("province_name") or row["_id"]["province_id"],
            municipality_id=row["_id"]["municipality_id"],
            municipality_name=row["_id"].get("municipality_name")
            or row["_id"]["municipality_id"],
            count=int(row["count"]),
        )
        for row in facet.get("municipalities") or []
        if row.get("_id") and row["_id"].get("municipality_id")
    ]

    return AdminOrdersByLocation(
        granularity=granularity,
        year=year,
        month=month,
        period_label=period_label,
        total_orders=total,
        without_location=without_location,
        provinces=provinces,
        municipalities=municipalities,
    )
