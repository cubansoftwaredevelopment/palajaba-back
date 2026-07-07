from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NamedTuple

from fastapi import HTTPException, status

from app.database import (
    get_catalog_products_collection,
    get_orders_collection,
    get_seller_profile_views_collection,
)
from app.schemas.seller_stats import (
    CurrencyRevenueSeries,
    CurrencyTotal,
    PeriodComparison,
    ProductsSoldDataPoint,
    RevenueDataPoint,
    SellerProductsSoldChart,
    SellerRevenueChart,
    SellerRevenueTotals,
    SellerStatsPeriod,
    SellerStatsSummary,
    SellerTopProductItem,
    SellerTopProducts,
    STAT_REVENUE_CURRENCIES,
)
from app.services.order_totals import compute_order_products_revenue
from app.services.plans import seller_has_statistics
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.month_bounds import (
    compare_month,
    current_month_year,
    iter_months,
    month_bounds,
    months_between_inclusive,
)

Granularity = Literal["daily", "weekly", "monthly"]

TOP_PRODUCTS_LIMIT = 5
TOP_SOLD_LOOKUP_BUFFER = 50

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


async def ensure_seller_stats_indexes() -> None:
    views = get_seller_profile_views_collection()
    await views.create_index([("seller_id", 1), ("viewed_at", -1)])

    orders = get_orders_collection()
    await orders.create_index([("seller_id", 1), ("status", 1), ("completed_at", -1)])
    await orders.create_index(
        [("seller_id", 1), ("status", 1), ("payment_currency", 1)],
        name="seller_completed_payment_currency",
    )

    products = get_catalog_products_collection()
    await products.create_index(
        [("seller_id", 1), ("is_available", 1), ("view_only", 1)],
        name="seller_active_products",
    )

    await backfill_order_collected_totals()


def normalize_currency_totals(rows: list[dict[str, Any]]) -> tuple[list[CurrencyTotal], int]:
    """Normaliza filas de agregación MongoDB a las cuatro monedas con 0 por defecto."""
    by_currency = {
        str(row.get("_id")): row
        for row in rows
        if row.get("_id") in STAT_REVENUE_CURRENCIES
    }
    totals: list[CurrencyTotal] = []
    orders_count = 0
    for code in STAT_REVENUE_CURRENCIES:
        row = by_currency.get(code, {})
        amount = round(float(row.get("total", 0.0)), 2)
        if code == "CUP":
            amount = float(round(amount))
        totals.append(CurrencyTotal(currency=code, amount=amount))
        orders_count += int(row.get("orders_count", 0))
    return totals, orders_count


async def backfill_order_collected_totals() -> int:
    """Persiste collected_total en pedidos completados legacy (solo productos, sin domicilio)."""
    orders = get_orders_collection()
    cursor = orders.find(
        {
            "status": "completed",
            "$or": [
                {"collected_total": {"$exists": False}},
                {"collected_total": None},
            ],
        },
        projection={
            "status": 1,
            "items": 1,
            "payment_currency": 1,
        },
    )

    updated = 0
    async for doc in cursor:
        revenue = compute_order_products_revenue(doc)
        if revenue is None:
            continue
        _, amount = revenue
        await orders.update_one(
            {"_id": doc["_id"]},
            {"$set": {"collected_total": amount}},
        )
        updated += 1
    return updated


async def get_seller_revenue_totals(
    seller_id: str,
    seller_doc: dict,
    *,
    year: int | None = None,
    month: int | None = None,
) -> SellerRevenueTotals:
    if not seller_has_statistics(seller_doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las estadísticas están disponibles en el plan Premium.",
        )

    target_year, target_month = year, month
    if target_year is None or target_month is None:
        target_year, target_month = current_month_year()

    _validate_stats_month(seller_doc, target_year, target_month)
    start, end = month_bounds(target_year, target_month)

    pipeline = [
        {
            "$match": {
                "seller_id": seller_id,
                "status": "completed",
                "completed_at": {"$gte": start, "$lt": end},
                "payment_currency": {"$in": list(STAT_REVENUE_CURRENCIES)},
                "collected_total": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$payment_currency",
                "total": {"$sum": "$collected_total"},
                "orders_count": {"$sum": 1},
            }
        },
    ]

    rows = await get_orders_collection().aggregate(pipeline).to_list(length=None)
    totals, orders_count = normalize_currency_totals(rows)

    return SellerRevenueTotals(
        year=target_year,
        month=target_month,
        totals=totals,
        orders_count=orders_count,
    )


async def record_profile_view(seller_id: str) -> None:
    now = to_utc_naive(utc_now())
    await get_seller_profile_views_collection().insert_one(
        {"seller_id": seller_id, "viewed_at": now},
    )


def _seller_earliest_month(seller_doc: dict[str, Any]) -> tuple[int, int]:
    joined_at = seller_doc.get("approved_at") or seller_doc.get("created_at")
    if not isinstance(joined_at, datetime):
        return current_month_year()
    if joined_at.tzinfo is not None:
        joined_at = to_utc_naive(joined_at)
    return joined_at.year, joined_at.month


def _build_stats_period(seller_doc: dict[str, Any]) -> SellerStatsPeriod:
    earliest_year, earliest_month = _seller_earliest_month(seller_doc)
    current_year, current_month = current_month_year()
    return SellerStatsPeriod(
        earliest_year=earliest_year,
        earliest_month=earliest_month,
        current_year=current_year,
        current_month=current_month,
        months_available=months_between_inclusive(
            earliest_year,
            earliest_month,
            current_year,
            current_month,
        ),
    )


def _validate_stats_month(
    seller_doc: dict[str, Any],
    year: int,
    month: int,
) -> SellerStatsPeriod:
    period = _build_stats_period(seller_doc)

    if compare_month(year, month, period.earliest_year, period.earliest_month) < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay estadísticas antes de tu alta en la plataforma.",
        )

    if compare_month(year, month, period.current_year, period.current_month) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese mes aún no ha comenzado.",
        )

    return period


def _day_label(day: int, month: int) -> str:
    return f"{day} {SPANISH_MONTHS[month - 1]}"


def _month_label(year: int, month: int) -> str:
    return f"{SPANISH_MONTHS_FULL[month - 1].capitalize()} {year}"


class ComparisonWindow(NamedTuple):
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    period_label: str
    previous_period_label: str
    comparison_label: str


def _start_of_day(value: datetime) -> datetime:
    return datetime(value.year, value.month, value.day)


def _start_of_week_monday(value: datetime) -> datetime:
    day = _start_of_day(value)
    return day - timedelta(days=day.weekday())


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def resolve_comparison_window(
    granularity: Granularity,
    *,
    reference: datetime | None = None,
) -> ComparisonWindow:
    """Ventanas para comparar hoy/ayer, esta semana/anterior o este mes/anterior."""
    now = reference if reference is not None else to_utc_naive(utc_now())
    today = _start_of_day(now)

    if granularity == "daily":
        current_start = today
        current_end = today + timedelta(days=1)
        previous_start = today - timedelta(days=1)
        previous_end = today
        period_label = _day_label(today.day, today.month)
        previous_period_label = _day_label(previous_start.day, previous_start.month)
        comparison_label = "vs ayer"
    elif granularity == "weekly":
        week_start = _start_of_week_monday(today)
        elapsed_days = (today - week_start).days + 1
        current_start = week_start
        current_end = today + timedelta(days=1)
        previous_start = week_start - timedelta(days=7)
        previous_end = previous_start + timedelta(days=elapsed_days)
        period_label = f"Semana del {_day_label(week_start.day, week_start.month)}"
        previous_period_label = (
            f"Semana del {_day_label(previous_start.day, previous_start.month)}"
        )
        comparison_label = "vs semana pasada"
    else:
        current_year, current_month = today.year, today.month
        current_start, _ = month_bounds(current_year, current_month)
        current_end = today + timedelta(days=1)
        elapsed_days = (today - current_start).days + 1

        prev_year, prev_month = _previous_month(current_year, current_month)
        previous_start, prev_month_end = month_bounds(prev_year, prev_month)
        previous_end = previous_start + timedelta(days=elapsed_days)
        if previous_end > prev_month_end:
            previous_end = prev_month_end

        period_label = _month_label(current_year, current_month)
        previous_period_label = _month_label(prev_year, prev_month)
        comparison_label = "vs mes pasado"

    return ComparisonWindow(
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
        period_label=period_label,
        previous_period_label=previous_period_label,
        comparison_label=comparison_label,
    )


def compute_change_percent(current: float, previous: float) -> float:
    if previous == 0:
        if current == 0:
            return 0.0
        return 100.0
    return round((current - previous) / previous * 100, 1)


def comparison_available_for_seller(
    window: ComparisonWindow,
    seller_doc: dict[str, Any],
) -> bool:
    joined_at = seller_doc.get("approved_at") or seller_doc.get("created_at")
    if not isinstance(joined_at, datetime):
        return True
    if joined_at.tzinfo is not None:
        joined_at = to_utc_naive(joined_at)
    return joined_at < window.previous_start


def build_period_comparison(
    current_total: float,
    previous_total: float,
    window: ComparisonWindow,
    *,
    available: bool,
) -> PeriodComparison:
    if not available:
        return PeriodComparison(
            current_total=current_total,
            previous_total=previous_total,
            change_percent=None,
            comparison_available=False,
            period_label=window.period_label,
            previous_period_label=window.previous_period_label,
            comparison_label=window.comparison_label,
            direction="unavailable",
        )

    change_percent = compute_change_percent(current_total, previous_total)
    if change_percent > 0:
        direction: Literal["up", "down", "flat", "unavailable"] = "up"
    elif change_percent < 0:
        direction = "down"
    else:
        direction = "flat"

    return PeriodComparison(
        current_total=current_total,
        previous_total=previous_total,
        change_percent=change_percent,
        comparison_available=True,
        period_label=window.period_label,
        previous_period_label=window.previous_period_label,
        comparison_label=window.comparison_label,
        direction=direction,
    )


def _revenue_rows_to_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        currency = str(row.get("_id") or "").strip()
        if not currency:
            continue
        amount = float(row.get("total") or 0.0)
        if currency == "CUP":
            amount = float(round(amount))
        else:
            amount = round(amount, 2)
        totals[currency] = amount
    return totals


def _units_from_facet_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    return int(rows[0].get("total") or 0)


async def aggregate_period_comparison(
    seller_id: str,
    window: ComparisonWindow,
) -> tuple[dict[str, float], dict[str, float], int, int]:
    pipeline = [
        {
            "$match": {
                "seller_id": seller_id,
                "status": "completed",
                "completed_at": {
                    "$gte": window.previous_start,
                    "$lt": window.current_end,
                },
            }
        },
        {
            "$facet": {
                "current_revenue": [
                    {
                        "$match": {
                            "completed_at": {
                                "$gte": window.current_start,
                                "$lt": window.current_end,
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": "$payment_currency",
                            "total": {"$sum": {"$ifNull": ["$collected_total", 0]}},
                        }
                    },
                ],
                "previous_revenue": [
                    {
                        "$match": {
                            "completed_at": {
                                "$gte": window.previous_start,
                                "$lt": window.previous_end,
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": "$payment_currency",
                            "total": {"$sum": {"$ifNull": ["$collected_total", 0]}},
                        }
                    },
                ],
                "current_units": [
                    {
                        "$match": {
                            "completed_at": {
                                "$gte": window.current_start,
                                "$lt": window.current_end,
                            }
                        }
                    },
                    {"$unwind": "$items"},
                    {
                        "$group": {
                            "_id": None,
                            "total": {"$sum": "$items.quantity"},
                        }
                    },
                ],
                "previous_units": [
                    {
                        "$match": {
                            "completed_at": {
                                "$gte": window.previous_start,
                                "$lt": window.previous_end,
                            }
                        }
                    },
                    {"$unwind": "$items"},
                    {
                        "$group": {
                            "_id": None,
                            "total": {"$sum": "$items.quantity"},
                        }
                    },
                ],
            }
        },
    ]

    rows = await get_orders_collection().aggregate(pipeline).to_list(length=1)
    if not rows:
        return {}, {}, 0, 0

    facet = rows[0]
    current_revenue = _revenue_rows_to_map(facet.get("current_revenue") or [])
    previous_revenue = _revenue_rows_to_map(facet.get("previous_revenue") or [])
    current_units = _units_from_facet_rows(facet.get("current_units") or [])
    previous_units = _units_from_facet_rows(facet.get("previous_units") or [])
    return current_revenue, previous_revenue, current_units, previous_units


def _week_ranges_in_month(year: int, month: int, *, cap_at: datetime | None) -> list[tuple[str, str, datetime, datetime]]:
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


def _daily_ranges_in_month(year: int, month: int, *, cap_at: datetime | None) -> list[tuple[str, str, datetime, datetime]]:
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


def _monthly_ranges(period: SellerStatsPeriod) -> list[tuple[str, str, datetime, datetime]]:
    ranges: list[tuple[str, str, datetime, datetime]] = []
    for year, month in iter_months(
        period.earliest_year,
        period.earliest_month,
        period.current_year,
        period.current_month,
    ):
        start, end = month_bounds(year, month)
        key = f"{year:04d}-{month:02d}"
        label = _month_label(year, month)
        ranges.append((key, label, start, end))
    return ranges


def _resolve_chart_ranges(
    seller_doc: dict[str, Any],
    granularity: Granularity,
    year: int | None,
    month: int | None,
) -> tuple[
    SellerStatsPeriod,
    list[tuple[str, str, datetime, datetime]],
    datetime,
    datetime,
    int | None,
    int | None,
]:
    period = _build_stats_period(seller_doc)

    if granularity == "monthly":
        if period.months_available < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Necesitas al menos dos meses en la plataforma para ver el rendimiento mensual.",
            )
        ranges = _monthly_ranges(period)
        range_start = ranges[0][2]
        range_end = ranges[-1][3]
        chart_year = None
        chart_month = None
    else:
        if year is None or month is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Indica el mes para ver el rendimiento diario o semanal.",
            )
        _validate_stats_month(seller_doc, year, month)
        chart_year, chart_month = year, month
        now = to_utc_naive(utc_now())
        is_current_month = year == period.current_year and month == period.current_month
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

    return period, ranges, range_start, range_end, chart_year, chart_month


def _order_products_sold_count(order: dict[str, Any]) -> int:
    if order.get("status") != "completed":
        return 0
    return sum(int(item.get("quantity", 0)) for item in (order.get("items") or []))


def _bucket_products_sold(
    orders: list[dict[str, Any]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> dict[str, int]:
    buckets = {key: 0 for key, _, _, _ in ranges}

    for order in orders:
        completed_at = order.get("completed_at")
        if not isinstance(completed_at, datetime):
            continue

        count = _order_products_sold_count(order)
        if count <= 0:
            continue

        for key, _, start, end in ranges:
            if start <= completed_at < end:
                buckets[key] += count
                break

    return buckets


def _bucket_completed_orders(
    orders: list[dict[str, Any]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> dict[str, dict[str, float]]:
    buckets = {key: {} for key, _, _, _ in ranges}

    for order in orders:
        completed_at = order.get("completed_at")
        if not isinstance(completed_at, datetime):
            continue

        revenue = compute_order_products_revenue(order)
        if revenue is None:
            continue
        currency, amount = revenue
        if amount <= 0:
            continue

        for key, _, start, end in ranges:
            if start <= completed_at < end:
                buckets[key][currency] = buckets[key].get(currency, 0.0) + amount
                break

    return buckets


def _series_from_buckets(
    buckets: dict[str, dict[str, float]],
    ordered_keys: list[tuple[str, str]],
) -> list[CurrencyRevenueSeries]:
    currencies = sorted(
        {
            currency
            for amounts in buckets.values()
            for currency in amounts
        }
    )

    series: list[CurrencyRevenueSeries] = []
    for currency in currencies:
        points: list[RevenueDataPoint] = []
        total = 0.0
        for key, label in ordered_keys:
            amount = round(buckets.get(key, {}).get(currency, 0.0), 2)
            total += amount
            points.append(RevenueDataPoint(key=key, label=label, amount=amount))

        total = round(total, 2)
        if total <= 0:
            continue

        series.append(
            CurrencyRevenueSeries(
                currency=currency,
                total=total,
                points=points,
            )
        )

    return series


def _attach_revenue_comparisons(
    series: list[CurrencyRevenueSeries],
    *,
    window: ComparisonWindow,
    available: bool,
    current_revenue: dict[str, float],
    previous_revenue: dict[str, float],
) -> list[CurrencyRevenueSeries]:
    enriched: list[CurrencyRevenueSeries] = []
    for item in series:
        comparison = build_period_comparison(
            current_revenue.get(item.currency, 0.0),
            previous_revenue.get(item.currency, 0.0),
            window,
            available=available,
        )
        enriched.append(item.model_copy(update={"comparison": comparison}))
    return enriched


async def get_seller_stats_summary(
    seller_id: str,
    seller_doc: dict,
    *,
    year: int | None = None,
    month: int | None = None,
) -> SellerStatsSummary:
    if not seller_has_statistics(seller_doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las estadísticas están disponibles en el plan Premium.",
        )

    target_year, target_month = year, month
    if target_year is None or target_month is None:
        target_year, target_month = current_month_year()

    period = _validate_stats_month(seller_doc, target_year, target_month)
    start, end = month_bounds(target_year, target_month)

    profile_views = await get_seller_profile_views_collection().count_documents(
        {
            "seller_id": seller_id,
            "viewed_at": {"$gte": start, "$lt": end},
        }
    )

    confirmed_orders = await get_orders_collection().count_documents(
        {
            "seller_id": seller_id,
            "status": "completed",
            "completed_at": {"$gte": start, "$lt": end},
        }
    )

    active_products = await get_catalog_products_collection().count_documents(
        {
            "seller_id": seller_id,
            "is_available": True,
            "view_only": {"$ne": True},
        }
    )

    return SellerStatsSummary(
        year=target_year,
        month=target_month,
        profile_views=profile_views,
        confirmed_orders=confirmed_orders,
        active_products=active_products,
        period=period,
    )


async def get_seller_revenue_chart(
    seller_id: str,
    seller_doc: dict,
    *,
    granularity: Granularity,
    year: int | None = None,
    month: int | None = None,
) -> SellerRevenueChart:
    if not seller_has_statistics(seller_doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las estadísticas están disponibles en el plan Premium.",
        )

    period, ranges, range_start, range_end, chart_year, chart_month = _resolve_chart_ranges(
        seller_doc,
        granularity,
        year,
        month,
    )

    orders = await get_orders_collection().find(
        {
            "seller_id": seller_id,
            "status": "completed",
            "completed_at": {"$gte": range_start, "$lt": range_end},
        }
    ).to_list(length=None)

    ordered_keys = [(key, label) for key, label, _, _ in ranges]
    buckets = _bucket_completed_orders(orders, ranges)
    series = _series_from_buckets(buckets, ordered_keys)

    window = resolve_comparison_window(granularity)
    available = comparison_available_for_seller(window, seller_doc)
    current_revenue, previous_revenue, _, _ = await aggregate_period_comparison(
        seller_id,
        window,
    )
    series = _attach_revenue_comparisons(
        series,
        window=window,
        available=available,
        current_revenue=current_revenue,
        previous_revenue=previous_revenue,
    )

    return SellerRevenueChart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        months_available=period.months_available,
        series=series,
    )


async def get_seller_products_sold_chart(
    seller_id: str,
    seller_doc: dict,
    *,
    granularity: Granularity,
    year: int | None = None,
    month: int | None = None,
) -> SellerProductsSoldChart:
    if not seller_has_statistics(seller_doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las estadísticas están disponibles en el plan Premium.",
        )

    period, ranges, range_start, range_end, chart_year, chart_month = _resolve_chart_ranges(
        seller_doc,
        granularity,
        year,
        month,
    )

    orders = await get_orders_collection().find(
        {
            "seller_id": seller_id,
            "status": "completed",
            "completed_at": {"$gte": range_start, "$lt": range_end},
        }
    ).to_list(length=None)

    buckets = _bucket_products_sold(orders, ranges)
    ordered_keys = [(key, label) for key, label, _, _ in ranges]
    points: list[ProductsSoldDataPoint] = []
    total = 0
    for key, label in ordered_keys:
        count = buckets.get(key, 0)
        total += count
        points.append(ProductsSoldDataPoint(key=key, label=label, count=count))

    window = resolve_comparison_window(granularity)
    available = comparison_available_for_seller(window, seller_doc)
    _, _, current_units, previous_units = await aggregate_period_comparison(
        seller_id,
        window,
    )
    comparison = build_period_comparison(
        float(current_units),
        float(previous_units),
        window,
        available=available,
    )

    return SellerProductsSoldChart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        months_available=period.months_available,
        total=total,
        points=points,
        comparison=comparison,
    )


def _product_to_top_item(
    doc: dict[str, Any],
    *,
    popularity: int | None = None,
    units_sold: int | None = None,
) -> SellerTopProductItem:
    return SellerTopProductItem(
        product_id=str(doc["_id"]),
        name=doc.get("name") or "Producto",
        image_url=doc.get("image_url"),
        popularity=popularity,
        units_sold=units_sold,
    )


async def get_seller_top_products(
    seller_id: str,
    seller_doc: dict,
) -> SellerTopProducts:
    if not seller_has_statistics(seller_doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las estadísticas están disponibles en el plan Premium.",
        )

    products_col = get_catalog_products_collection()

    popular_docs = await products_col.find(
        {
            "seller_id": seller_id,
            "view_only": {"$ne": True},
        },
        {"name": 1, "image_url": 1, "popularity": 1},
    ).sort([("popularity", -1), ("name", 1)]).limit(TOP_PRODUCTS_LIMIT).to_list(length=TOP_PRODUCTS_LIMIT)

    most_popular = [
        _product_to_top_item(
            doc,
            popularity=int(doc.get("popularity") or 0),
        )
        for doc in popular_docs
    ]

    sold_pipeline = [
        {
            "$match": {
                "seller_id": seller_id,
                "status": "completed",
            }
        },
        {"$unwind": "$items"},
        {
            "$group": {
                "_id": "$items.product_id",
                "units_sold": {"$sum": "$items.quantity"},
            }
        },
        {"$sort": {"units_sold": -1}},
        {"$limit": TOP_SOLD_LOOKUP_BUFFER},
    ]
    sold_rows = await get_orders_collection().aggregate(sold_pipeline).to_list(
        length=TOP_SOLD_LOOKUP_BUFFER,
    )

    sold_product_ids: list[str] = []
    units_by_product: dict[str, int] = {}
    for row in sold_rows:
        product_id = str(row.get("_id") or "").strip()
        if not product_id:
            continue
        sold_product_ids.append(product_id)
        units_by_product[product_id] = int(row.get("units_sold") or 0)

    product_docs_by_id: dict[str, dict[str, Any]] = {}
    if sold_product_ids:
        from bson import ObjectId
        from bson.errors import InvalidId

        object_ids: list[ObjectId] = []
        for product_id in sold_product_ids:
            try:
                object_ids.append(ObjectId(product_id))
            except InvalidId:
                continue

        if object_ids:
            async for doc in products_col.find(
                {"_id": {"$in": object_ids}, "seller_id": seller_id},
            ):
                product_docs_by_id[str(doc["_id"])] = doc

    most_sold: list[SellerTopProductItem] = []
    for product_id in sold_product_ids:
        doc = product_docs_by_id.get(product_id)
        if not doc:
            continue
        most_sold.append(
            _product_to_top_item(
                doc,
                units_sold=units_by_product[product_id],
            )
        )
        if len(most_sold) >= TOP_PRODUCTS_LIMIT:
            break

    return SellerTopProducts(
        most_popular=most_popular,
        most_sold=most_sold,
    )
