from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.database import (
    get_catalog_products_collection,
    get_orders_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
    get_seller_profile_views_collection,
)
from app.seller_statistics.schemas import (
    CurrencyTotal,
    HighViewsLowSales,
    ProductConversion,
    ProductConversionItem,
    RevenueChart,
    RevenueSeries,
    SellerStatsKpis,
    SeriesChart,
    SeriesPoint,
    SiteConversion,
    TopSold,
    TopSoldItem,
    ViewsByZone,
    ZoneView,
)
from app.constants import MUNICIPALITIES_BY_PROVINCE, PROVINCE_NAMES
from app.subscriptions.service import STATISTICS_PLAN_REQUIRED_MESSAGE, seller_has_statistics
from app.services.seller_stats import Granularity
from app.statistics_admin.utils import parse_inclusive_dates, ranges_between
from app.utils.datetime import to_utc_naive, utc_now

HIGH_VIEWS_LOW_SALES_LIMIT = 10
TOP_SOLD_LIMIT = 8
UNKNOWN_ZONE = "Sin zona"


async def _seller_doc(seller_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(seller_id)
    except InvalidId as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada.") from exc

    doc = await get_registrations_collection().find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada.")
    if not seller_has_statistics(doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=STATISTICS_PLAN_REQUIRED_MESSAGE,
        )
    return doc


def resolve_window(
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> tuple[datetime, datetime]:
    parsed = parse_inclusive_dates(start, end)
    if parsed:
        return parsed

    now = to_utc_naive(utc_now())
    today = date(now.year, now.month, now.day)
    if granularity == "daily":
        window = parse_inclusive_dates(today, today)
    elif granularity == "weekly":
        window = parse_inclusive_dates(today - timedelta(days=6), today)
    else:
        window = parse_inclusive_dates(date(today.year, today.month, 1), today)
    if window is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rango de fechas no válido.")
    return window


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _as_naive(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return to_utc_naive(value) if value.tzinfo is not None else value


def _bucket_counts(
    moments: list[datetime],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> list[SeriesPoint]:
    buckets = {key: 0 for key, _, _, _ in ranges}
    for moment in moments:
        for key, _, start, end in ranges:
            if start <= moment < end:
                buckets[key] += 1
                break
    return [SeriesPoint(key=key, label=label, value=buckets[key]) for key, label, _, _ in ranges]


def _bucket_amounts(
    rows: list[tuple[datetime, float]],
    ranges: list[tuple[str, str, datetime, datetime]],
) -> list[SeriesPoint]:
    buckets = {key: 0.0 for key, _, _, _ in ranges}
    for moment, amount in rows:
        for key, _, start, end in ranges:
            if start <= moment < end:
                buckets[key] += amount
                break
    return [
        SeriesPoint(key=key, label=label, value=round(buckets[key], 2))
        for key, label, _, _ in ranges
    ]


async def _profile_view_moments(seller_id: str, start: datetime, end: datetime) -> list[datetime]:
    moments: list[datetime] = []
    async for doc in get_seller_profile_views_collection().find(
        {"seller_id": seller_id, "viewed_at": {"$gte": start, "$lt": end}},
        {"viewed_at": 1},
    ):
        moment = _as_naive(doc.get("viewed_at"))
        if moment:
            moments.append(moment)
    return moments


async def _event_moments(
    seller_id: str,
    event: str,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    moments: list[datetime] = []
    async for doc in get_product_popularity_events_collection().find(
        {
            "seller_id": seller_id,
            "event": event,
            "created_at": {"$gte": start, "$lt": end},
        },
        {"created_at": 1},
    ):
        moment = _as_naive(doc.get("created_at"))
        if moment:
            moments.append(moment)
    return moments


async def _completed_orders(seller_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    return await get_orders_collection().find(
        {
            "seller_id": seller_id,
            "status": "completed",
            "completed_at": {"$gte": start, "$lt": end},
        },
        {
            "completed_at": 1,
            "collected_total": 1,
            "payment_currency": 1,
            "items": 1,
        },
    ).to_list(length=None)


async def _catalog_by_id(product_ids: list[str]) -> dict[str, dict[str, Any]]:
    object_ids: list[ObjectId] = []
    for product_id in product_ids:
        try:
            object_ids.append(ObjectId(product_id))
        except (InvalidId, TypeError):
            continue
    if not object_ids:
        return {}
    found: dict[str, dict[str, Any]] = {}
    async for doc in get_catalog_products_collection().find(
        {"_id": {"$in": object_ids}},
        {"name": 1, "image_url": 1},
    ):
        found[str(doc["_id"])] = doc
    return found


async def get_kpis(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> SellerStatsKpis:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    visitors = await get_seller_profile_views_collection().count_documents(
        {"seller_id": seller_id, "viewed_at": {"$gte": range_start, "$lt": range_end}},
    )
    product_views = await get_product_popularity_events_collection().count_documents(
        {
            "seller_id": seller_id,
            "event": "view",
            "created_at": {"$gte": range_start, "$lt": range_end},
        },
    )
    jabas = await get_product_popularity_events_collection().count_documents(
        {
            "seller_id": seller_id,
            "event": "jaba",
            "created_at": {"$gte": range_start, "$lt": range_end},
        },
    )
    orders = await _completed_orders(seller_id, range_start, range_end)
    totals: dict[str, float] = {}
    for order in orders:
        currency = str(order.get("payment_currency") or "").strip().upper()
        amount = order.get("collected_total")
        if not currency or amount is None:
            continue
        totals[currency] = round(totals.get(currency, 0.0) + float(amount), 2)

    return SellerStatsKpis(
        visitors=visitors,
        product_views=product_views,
        delivered_orders=len(orders),
        revenue=[CurrencyTotal(currency=code, total=total) for code, total in sorted(totals.items())],
        site_jabas=jabas,
        site_conversion_rate=_rate(jabas, visitors),
    )


async def get_site_conversion(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> SiteConversion:
    kpis = await get_kpis(seller_id, granularity=granularity, start=start, end=end)
    return SiteConversion(visitors=kpis.visitors, jabas=kpis.site_jabas, rate=kpis.site_conversion_rate)


async def _product_conversion_items(
    seller_id: str,
    start: datetime,
    end: datetime,
) -> tuple[list[ProductConversionItem], int, int]:
    rows = await get_product_popularity_events_collection().aggregate(
        [
            {
                "$match": {
                    "seller_id": seller_id,
                    "event": {"$in": ["view", "purchase"]},
                    "created_at": {"$gte": start, "$lt": end},
                }
            },
            {
                "$group": {
                    "_id": {"product_id": "$product_id", "event": "$event"},
                    "count": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=None)

    views_by_product: dict[str, int] = {}
    purchases_by_product: dict[str, int] = {}
    for row in rows:
        key = row.get("_id") or {}
        product_id = str(key.get("product_id") or "")
        event = str(key.get("event") or "")
        count = int(row.get("count") or 0)
        if not product_id:
            continue
        if event == "view":
            views_by_product[product_id] = count
        elif event == "purchase":
            purchases_by_product[product_id] = count

    product_ids = sorted(set(views_by_product) | set(purchases_by_product))
    catalog = await _catalog_by_id(product_ids)
    items: list[ProductConversionItem] = []
    total_views = 0
    total_purchases = 0
    for product_id in product_ids:
        views = views_by_product.get(product_id, 0)
        purchases = purchases_by_product.get(product_id, 0)
        total_views += views
        total_purchases += purchases
        doc = catalog.get(product_id) or {}
        items.append(
            ProductConversionItem(
                product_id=product_id,
                name=str(doc.get("name") or "Producto eliminado"),
                image_url=doc.get("image_url"),
                views=views,
                purchases=purchases,
                conversion_rate=_rate(purchases, views),
            )
        )
    items.sort(key=lambda item: (-item.views, -item.purchases, item.name.lower()))
    return items, total_views, total_purchases


async def get_product_conversion(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> ProductConversion:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    items, total_views, total_purchases = await _product_conversion_items(seller_id, range_start, range_end)
    return ProductConversion(
        items=items,
        global_conversion_rate=_rate(total_purchases, total_views),
        total_views=total_views,
        total_purchases=total_purchases,
    )


async def get_high_views_low_sales(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> HighViewsLowSales:
    conversion = await get_product_conversion(seller_id, granularity=granularity, start=start, end=end)
    viewed = [item for item in conversion.items if item.views > 0]
    if not viewed:
        return HighViewsLowSales(items=[])

    views_sorted = sorted(item.views for item in viewed)
    median = views_sorted[len(views_sorted) // 2]
    min_views = max(5, median)
    global_rate = conversion.global_conversion_rate
    flagged = [
        item
        for item in viewed
        if item.views >= min_views
        and (item.conversion_rate < global_rate if global_rate > 0 else item.purchases == 0)
    ]
    flagged.sort(key=lambda item: (item.conversion_rate, -item.views))
    return HighViewsLowSales(items=flagged[:HIGH_VIEWS_LOW_SALES_LIMIT])


async def get_views_by_zone(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> ViewsByZone:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    rows = await get_seller_profile_views_collection().aggregate(
        [
            {
                "$match": {
                    "seller_id": seller_id,
                    "viewed_at": {"$gte": range_start, "$lt": range_end},
                }
            },
            {
                "$group": {
                    "_id": {
                        "province_id": {"$ifNull": ["$province_id", ""]},
                        "municipality_id": {"$ifNull": ["$municipality_id", ""]},
                    },
                    "views": {"$sum": 1},
                }
            },
            {"$sort": {"views": -1}},
        ]
    ).to_list(length=None)

    items: list[ZoneView] = []
    for row in rows:
        key = row.get("_id") or {}
        province_id = str(key.get("province_id") or "").strip()
        municipality_id = str(key.get("municipality_id") or "").strip()
        province_name = PROVINCE_NAMES.get(province_id, UNKNOWN_ZONE if not province_id else province_id)
        municipality_name = MUNICIPALITIES_BY_PROVINCE.get(province_id, {}).get(
            municipality_id,
            UNKNOWN_ZONE if not municipality_id else municipality_id,
        )
        items.append(
            ZoneView(
                province_id=province_id or "unknown",
                province_name=province_name,
                municipality_id=municipality_id or "unknown",
                municipality_name=municipality_name,
                views=int(row.get("views") or 0),
            )
        )
    return ViewsByZone(items=items)


async def get_traffic(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> SeriesChart:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    moments = await _profile_view_moments(seller_id, range_start, range_end)
    points = _bucket_counts(moments, ranges_between(range_start, range_end, granularity))
    return SeriesChart(total=float(len(moments)), points=points)


async def get_product_views(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> SeriesChart:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    moments = await _event_moments(seller_id, "view", range_start, range_end)
    points = _bucket_counts(moments, ranges_between(range_start, range_end, granularity))
    return SeriesChart(total=float(len(moments)), points=points)


async def get_delivered_orders(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> SeriesChart:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    orders = await _completed_orders(seller_id, range_start, range_end)
    moments: list[datetime] = []
    for order in orders:
        moment = _as_naive(order.get("completed_at"))
        if moment:
            moments.append(moment)
    points = _bucket_counts(moments, ranges_between(range_start, range_end, granularity))
    return SeriesChart(total=float(len(moments)), points=points)


async def get_revenue(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> RevenueChart:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    orders = await _completed_orders(seller_id, range_start, range_end)
    ranges = ranges_between(range_start, range_end, granularity)
    by_currency: dict[str, list[tuple[datetime, float]]] = {}
    for order in orders:
        currency = str(order.get("payment_currency") or "").strip().upper()
        amount = order.get("collected_total")
        moment = _as_naive(order.get("completed_at"))
        if not currency or amount is None or moment is None:
            continue
        by_currency.setdefault(currency, []).append((moment, float(amount)))

    series = [
        RevenueSeries(
            currency=currency,
            total=round(sum(amount for _, amount in rows), 2),
            points=_bucket_amounts(rows, ranges),
        )
        for currency, rows in sorted(by_currency.items())
    ]
    return RevenueChart(series=series)


async def get_top_sold(
    seller_id: str,
    *,
    granularity: Granularity,
    start: date | None,
    end: date | None,
) -> TopSold:
    await _seller_doc(seller_id)
    range_start, range_end = resolve_window(granularity, start, end)
    rows = await get_orders_collection().aggregate(
        [
            {
                "$match": {
                    "seller_id": seller_id,
                    "status": "completed",
                    "completed_at": {"$gte": range_start, "$lt": range_end},
                }
            },
            {"$unwind": "$items"},
            {
                "$group": {
                    "_id": "$items.product_id",
                    "units": {"$sum": {"$ifNull": ["$items.quantity", 0]}},
                }
            },
            {"$sort": {"units": -1}},
            {"$limit": TOP_SOLD_LIMIT},
        ]
    ).to_list(length=None)

    product_ids = [str(row["_id"]) for row in rows if row.get("_id")]
    catalog = await _catalog_by_id(product_ids)
    items: list[TopSoldItem] = []
    for row in rows:
        product_id = str(row.get("_id") or "")
        if not product_id:
            continue
        doc = catalog.get(product_id) or {}
        items.append(
            TopSoldItem(
                product_id=product_id,
                name=str(doc.get("name") or "Producto eliminado"),
                image_url=doc.get("image_url"),
                units_sold=int(row.get("units") or 0),
            )
        )
    return TopSold(items=items)
