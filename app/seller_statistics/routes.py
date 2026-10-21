from datetime import date

from fastapi import APIRouter, Depends, Query

from app.dependencies import require_seller
from app.seller_statistics import service
from app.seller_statistics.schemas import (
    HighViewsLowSales,
    ProductConversion,
    RevenueChart,
    SellerStatsKpis,
    SeriesChart,
    SiteConversion,
    TopSold,
    ViewsByZone,
)
from app.services.seller_stats import Granularity

router = APIRouter(prefix="/api/seller/statistics", tags=["seller-statistics"])


def _seller_id(payload: dict) -> str:
    return str(payload["seller_id"])


@router.get("/kpis", response_model=SellerStatsKpis)
async def seller_stats_kpis(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_kpis(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/conversion/site", response_model=SiteConversion)
async def seller_site_conversion(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_site_conversion(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/conversion/products", response_model=ProductConversion)
async def seller_product_conversion(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_product_conversion(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/conversion/high-views-low-sales", response_model=HighViewsLowSales)
async def seller_high_views_low_sales(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_high_views_low_sales(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/views-by-zone", response_model=ViewsByZone)
async def seller_views_by_zone(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_views_by_zone(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/traffic", response_model=SeriesChart)
async def seller_traffic(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_traffic(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/product-views", response_model=SeriesChart)
async def seller_product_views(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_product_views(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/orders", response_model=SeriesChart)
async def seller_delivered_orders(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_delivered_orders(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/revenue", response_model=RevenueChart)
async def seller_revenue(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_revenue(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )


@router.get("/top-sold", response_model=TopSold)
async def seller_top_sold(
    granularity: Granularity = Query(default="monthly"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    payload: dict = Depends(require_seller),
):
    return await service.get_top_sold(
        _seller_id(payload),
        granularity=granularity,
        start=start,
        end=end,
    )
