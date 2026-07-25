from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from app.database import (
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
    get_subscription_payments_collection,
)
from app.schemas.admin_stats import (
    AdminBusinessesByProvince,
    AdminProvinceBusinessCount,
    AdminRevenueChart,
    AdminStatsSummary,
)
from app.schemas.seller_stats import RevenueDataPoint
from app.services.cuba_locations import PROVINCE_NAMES
from app.services.seller_stats import (
    Granularity,
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


def _day_label(day: int, month: int) -> str:
    return f"{day} {SPANISH_MONTHS[month - 1]}"


def _month_label(year: int, month: int) -> str:
    return f"{SPANISH_MONTHS_FULL[month - 1].capitalize()} {year}"


async def _earliest_payment_month() -> tuple[int, int]:
    earliest = await get_subscription_payments_collection().find_one(
        {},
        sort=[("recorded_at", 1)],
        projection={"recorded_at": 1},
    )
    if earliest and isinstance(earliest.get("recorded_at"), datetime):
        recorded_at = earliest["recorded_at"]
        if recorded_at.tzinfo is not None:
            recorded_at = to_utc_naive(recorded_at)
        return recorded_at.year, recorded_at.month

    registration = await get_registrations_collection().find_one(
        {"approved_at": {"$exists": True, "$ne": None}},
        sort=[("approved_at", 1)],
        projection={"approved_at": 1},
    )
    if registration and isinstance(registration.get("approved_at"), datetime):
        approved_at = registration["approved_at"]
        if approved_at.tzinfo is not None:
            approved_at = to_utc_naive(approved_at)
        return approved_at.year, approved_at.month

    return current_month_year()


async def _admin_stats_period() -> dict[str, int]:
    earliest_year, earliest_month = await _earliest_payment_month()
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


def _validate_admin_month(period: dict[str, int], year: int, month: int) -> None:
    if compare_month(year, month, period["earliest_year"], period["earliest_month"]) < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay recaudación registrada antes de esa fecha.",
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


def _resolve_admin_chart_ranges(
    period: dict[str, int],
    granularity: Granularity,
    year: int | None,
    month: int | None,
) -> tuple[list[tuple[str, str, datetime, datetime]], datetime, datetime, int | None, int | None]:
    if granularity == "monthly":
        if period["months_available"] < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Necesitas al menos dos meses de recaudación para ver el gráfico mensual.",
            )
        ranges = _monthly_ranges(period)
        return ranges, ranges[0][2], ranges[-1][3], None, None

    if year is None or month is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica el mes para ver el rendimiento diario o semanal.",
        )

    _validate_admin_month(period, year, month)
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


def _bucket_payments(
    payments: list[dict[str, Any]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> dict[str, float]:
    buckets = {key: 0.0 for key, _, _, _ in ranges}

    for payment in payments:
        recorded_at = payment.get("recorded_at")
        if not isinstance(recorded_at, datetime):
            continue
        if recorded_at.tzinfo is not None:
            recorded_at = to_utc_naive(recorded_at)

        amount = float(payment.get("amount_cup") or 0)
        if amount <= 0:
            continue

        for key, _, start, end in ranges:
            if start <= recorded_at < end:
                buckets[key] += amount
                break

    return buckets


async def _sum_payments_between(start: datetime, end: datetime) -> tuple[float, int]:
    pipeline = [
        {"$match": {"recorded_at": {"$gte": start, "$lt": end}, "amount_cup": {"$gt": 0}}},
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$amount_cup"},
                "count": {"$sum": 1},
            }
        },
    ]
    rows = await get_subscription_payments_collection().aggregate(pipeline).to_list(length=1)
    if not rows:
        return 0.0, 0
    return float(rows[0].get("total") or 0), int(rows[0].get("count") or 0)


async def get_stats_summary(year: int, month: int) -> AdminStatsSummary:
    collection = get_subscription_payments_collection()
    start, end = month_bounds(year, month)
    now = to_utc_naive(utc_now())

    payments_pipeline = [
        {
            "$match": {
                "recorded_at": {"$gte": start, "$lt": end},
                "amount_cup": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$amount_cup"},
                "count": {"$sum": 1},
            }
        },
    ]
    payments_result = await collection.aggregate(payments_pipeline).to_list(length=1)
    payments_total = int(payments_result[0]["total"]) if payments_result else 0
    payments_count = int(payments_result[0]["count"]) if payments_result else 0

    registrations = get_registrations_collection()
    active_stores = await registrations.count_documents(
        {
            "status": "approved",
            "subscription_ends_at": {"$gt": now},
        }
    )
    pending_registrations = await registrations.count_documents({"status": "pending"})

    published_products = await get_catalog_products_collection().count_documents({})
    orders_total = await get_orders_collection().count_documents({})

    return AdminStatsSummary(
        year=year,
        month=month,
        payments_total_cup=payments_total,
        payments_count=payments_count,
        active_stores=active_stores,
        pending_registrations=pending_registrations,
        published_products=published_products,
        orders_total=orders_total,
    )


async def get_revenue_chart(
    *,
    granularity: Granularity,
    year: int | None = None,
    month: int | None = None,
) -> AdminRevenueChart:
    period = await _admin_stats_period()
    ranges, range_start, range_end, chart_year, chart_month = _resolve_admin_chart_ranges(
        period,
        granularity,
        year,
        month,
    )

    payments = await get_subscription_payments_collection().find(
        {
            "recorded_at": {"$gte": range_start, "$lt": range_end},
            "amount_cup": {"$gt": 0},
        }
    ).to_list(length=None)

    buckets = _bucket_payments(payments, ranges)
    points: list[RevenueDataPoint] = []
    total_cup = 0.0
    for key, label, _, _ in ranges:
        amount = round(buckets.get(key, 0.0))
        total_cup += amount
        points.append(RevenueDataPoint(key=key, label=label, amount=float(amount)))

    window = resolve_comparison_window(granularity)
    current_total, _ = await _sum_payments_between(window.current_start, window.current_end)
    previous_total, _ = await _sum_payments_between(window.previous_start, window.previous_end)

    first_payment_at = None
    earliest = await get_subscription_payments_collection().find_one(
        {},
        sort=[("recorded_at", 1)],
        projection={"recorded_at": 1},
    )
    if earliest and isinstance(earliest.get("recorded_at"), datetime):
        first_payment_at = earliest["recorded_at"]
        if first_payment_at.tzinfo is not None:
            first_payment_at = to_utc_naive(first_payment_at)

    comparison_available = (
        first_payment_at is not None and first_payment_at < window.previous_start
    )
    comparison = build_period_comparison(
        current_total,
        previous_total,
        window,
        available=comparison_available,
    )

    return AdminRevenueChart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        months_available=period["months_available"],
        total_cup=int(round(total_cup)),
        payments_count=len(payments),
        points=points,
        comparison=comparison,
    )


async def get_businesses_by_province() -> AdminBusinessesByProvince:
    collection = get_registrations_collection()

    pipeline = [
        {"$match": {"status": "approved", "business_area.province_id": {"$exists": True, "$ne": ""}}},
        {
            "$group": {
                "_id": "$business_area.province_id",
                "province_name": {"$first": "$business_area.province_name"},
                "count": {"$sum": 1},
            }
        },
    ]
    grouped = await collection.aggregate(pipeline).to_list(length=None)
    counts_by_id = {row["_id"]: int(row["count"]) for row in grouped}

    provinces: list[AdminProvinceBusinessCount] = []
    for province_id, province_name in PROVINCE_NAMES.items():
        count = counts_by_id.get(province_id, 0)
        if count > 0:
            provinces.append(
                AdminProvinceBusinessCount(
                    province_id=province_id,
                    province_name=province_name,
                    count=count,
                )
            )

    provinces.sort(key=lambda item: (-item.count, item.province_name))

    without_location = await collection.count_documents(
        {
            "status": "approved",
            "$or": [
                {"business_area": {"$exists": False}},
                {"business_area.province_id": {"$exists": False}},
                {"business_area.province_id": ""},
            ],
        }
    )
    total_with_location = sum(item.count for item in provinces)

    return AdminBusinessesByProvince(
        total_with_location=total_with_location,
        without_location=without_location,
        provinces=provinces,
    )
