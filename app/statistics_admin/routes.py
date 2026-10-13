import calendar
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query

from app.dependencies import require_admin
from app.services.seller_stats import Granularity
from app.statistics_admin import devices as devices_service
from app.statistics_admin import orders as order_stats_service
from app.statistics_admin import products as product_stats_service
from app.statistics_admin import stats as stats_service
from app.statistics_admin import traffic as traffic_service
from app.statistics_admin.schemas import (
    AdminBusinessesByProvince,
    AdminDeliveryMap,
    AdminDeviceStats,
    AdminOrdersByLocation,
    AdminOrdersChart,
    AdminRevenueChart,
    AdminSalesChart,
    AdminStatsSummary,
    AdminTopBusinesses,
    AdminTopPopularProducts,
    AdminTopSoldProducts,
    AdminTrafficByLocation,
    AdminTrafficChart,
    AdminTrafficPatterns,
    DevicePresenceRequest,
    DevicePresenceResult,
    MarketplaceVisitRecordResult,
    MarketplaceVisitRequest,
    OrdersGranularity,
    TrafficGranularity,
)
from app.statistics_admin.utils import parse_inclusive_dates

router = APIRouter(prefix="/api/admin", tags=["statistics"])
public_router = APIRouter(prefix="/api/marketplace", tags=["statistics"])


def _resolved_window(start: date | None, end: date | None):
    return parse_inclusive_dates(start, end)


def _chart_bounds(granularity: str, year: int | None, month: int | None, start: date | None, end: date | None):
    window = _resolved_window(start, end)
    now = datetime.now(UTC)
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    use_default_month = window is None and granularity != "monthly"
    return (
        None if not use_default_month else target_year,
        None if not use_default_month else target_month,
        None if window is None else window[0],
        None if window is None else window[1],
    )


@router.get("/stats/summary", response_model=AdminStatsSummary)
async def stats_summary(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    _: dict = Depends(require_admin),
):
    now = datetime.now(UTC)
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return await stats_service.get_stats_summary(target_year, target_month)


@router.get("/stats/businesses-by-province", response_model=AdminBusinessesByProvince)
async def businesses_by_province(_: dict = Depends(require_admin)):
    return await stats_service.get_businesses_by_province()


@router.get("/stats/revenue", response_model=AdminRevenueChart)
async def stats_revenue(
    granularity: Granularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    chart_year, chart_month, range_start, range_end = _chart_bounds(granularity, year, month, start, end)
    return await stats_service.get_revenue_chart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        start=range_start,
        end=range_end,
    )


@router.get("/stats/traffic", response_model=AdminTrafficChart)
async def stats_traffic(
    granularity: TrafficGranularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    chart_year, chart_month, range_start, range_end = _chart_bounds(granularity, year, month, start, end)
    return await traffic_service.get_traffic_chart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        start=range_start,
        end=range_end,
    )


@router.get("/stats/traffic/locations", response_model=AdminTrafficByLocation)
async def stats_traffic_locations(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    now = datetime.now(UTC)
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return await traffic_service.get_traffic_by_location(
        year=target_year,
        month=target_month,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@router.get("/stats/traffic/patterns", response_model=AdminTrafficPatterns)
async def stats_traffic_patterns(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    now = datetime.now(UTC)
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return await traffic_service.get_traffic_patterns(
        year=target_year,
        month=target_month,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@router.get("/stats/orders", response_model=AdminOrdersChart)
async def stats_orders(
    granularity: OrdersGranularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    chart_year, chart_month, range_start, range_end = _chart_bounds(granularity, year, month, start, end)
    return await order_stats_service.get_orders_chart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        start=range_start,
        end=range_end,
    )


@router.get("/stats/orders/sales", response_model=AdminSalesChart)
async def stats_order_sales(
    granularity: OrdersGranularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    chart_year, chart_month, range_start, range_end = _chart_bounds(granularity, year, month, start, end)
    return await order_stats_service.get_sales_chart(
        granularity=granularity,
        year=chart_year,
        month=chart_month,
        start=range_start,
        end=range_end,
    )


@router.get("/stats/devices", response_model=AdminDeviceStats)
async def stats_devices(
    granularity: OrdersGranularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    if window is None:
        now = datetime.now(UTC)
        today = date(now.year, now.month, now.day)
        if granularity == "monthly":
            earliest = await devices_service.earliest_device_day()
            window = parse_inclusive_dates(earliest or date(today.year, today.month, 1), today)
        else:
            target_year = year if year is not None else now.year
            target_month = month if month is not None else now.month
            if (target_year, target_month) == (now.year, now.month):
                end_day = today
            else:
                last_day = calendar.monthrange(target_year, target_month)[1]
                end_day = date(target_year, target_month, last_day)
            window = parse_inclusive_dates(date(target_year, target_month, 1), end_day)
    assert window is not None
    return await devices_service.get_device_stats(
        granularity=granularity,
        start=window[0],
        end=window[1],
    )


@router.get("/stats/orders/top-businesses", response_model=AdminTopBusinesses)
async def stats_orders_top_businesses(
    granularity: OrdersGranularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    return await order_stats_service.get_top_businesses(
        granularity=granularity,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@router.get("/stats/products/sold", response_model=AdminTopSoldProducts)
async def stats_top_sold_products(
    granularity: OrdersGranularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    return await product_stats_service.get_top_sold_products(
        granularity=granularity,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@router.get("/stats/products/popular", response_model=AdminTopPopularProducts)
async def stats_top_popular_products(
    granularity: OrdersGranularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    return await product_stats_service.get_top_popular_products(
        granularity=granularity,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@router.get("/stats/orders/delivery-map", response_model=AdminDeliveryMap)
async def stats_orders_delivery_map(
    granularity: OrdersGranularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    return await order_stats_service.get_delivery_map(
        granularity=granularity,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@router.get("/stats/orders/locations", response_model=AdminOrdersByLocation)
async def stats_orders_locations(
    granularity: OrdersGranularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    window = _resolved_window(start, end)
    return await order_stats_service.get_orders_by_location(
        granularity=granularity,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


@public_router.post("/visits", response_model=MarketplaceVisitRecordResult)
async def record_marketplace_visit(payload: MarketplaceVisitRequest):
    return await traffic_service.record_marketplace_visit(payload)


@public_router.post("/devices/presence", response_model=DevicePresenceResult)
async def record_device_presence(payload: DevicePresenceRequest):
    await devices_service.record_device_presence(payload)
    return DevicePresenceResult()
