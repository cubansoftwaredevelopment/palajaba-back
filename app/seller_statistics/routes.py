from datetime import date

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_registrations_collection
from app.auth.utils import require_seller
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
from app.schemas.seller_stats import (
    SellerProductsSoldChart,
    SellerRevenueChart,
    SellerStatsSummary,
    SellerTopProducts,
)
from app.services import seller_stats as seller_stats_service
from app.services.seller_stats import Granularity

router = APIRouter()
stats_router = APIRouter(prefix="/api/seller/statistics", tags=["seller-statistics"])
auth_stats_router = APIRouter(prefix="/api/auth", tags=["auth"])


def _seller_id(payload: dict) -> str:
    return str(payload["seller_id"])


@stats_router.get("/kpis", response_model=SellerStatsKpis)
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


@stats_router.get("/conversion/site", response_model=SiteConversion)
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


@stats_router.get("/conversion/products", response_model=ProductConversion)
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


@stats_router.get("/conversion/high-views-low-sales", response_model=HighViewsLowSales)
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


@stats_router.get("/views-by-zone", response_model=ViewsByZone)
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


@stats_router.get("/traffic", response_model=SeriesChart)
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


@stats_router.get("/product-views", response_model=SeriesChart)
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


@stats_router.get("/orders", response_model=SeriesChart)
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


@stats_router.get("/revenue", response_model=RevenueChart)
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


@stats_router.get("/top-sold", response_model=TopSold)
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


async def _seller_doc(seller_id: str) -> dict:
    seller = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )
    return seller


@auth_stats_router.get("/me/stats/summary", response_model=SellerStatsSummary)
async def seller_stats_summary(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    seller_payload: dict = Depends(require_seller),
):
    seller = await _seller_doc(seller_payload["seller_id"])
    return await seller_stats_service.get_seller_stats_summary(
        seller_payload["seller_id"],
        seller,
        year=year,
        month=month,
    )


@auth_stats_router.get("/me/stats/revenue", response_model=SellerRevenueChart)
async def seller_revenue_chart(
    granularity: Granularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    seller_payload: dict = Depends(require_seller),
):
    seller = await _seller_doc(seller_payload["seller_id"])
    return await seller_stats_service.get_seller_revenue_chart(
        seller_payload["seller_id"],
        seller,
        granularity=granularity,
        year=year,
        month=month,
    )


@auth_stats_router.get("/me/stats/products-sold", response_model=SellerProductsSoldChart)
async def seller_products_sold_chart(
    granularity: Granularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    seller_payload: dict = Depends(require_seller),
):
    seller = await _seller_doc(seller_payload["seller_id"])
    return await seller_stats_service.get_seller_products_sold_chart(
        seller_payload["seller_id"],
        seller,
        granularity=granularity,
        year=year,
        month=month,
    )


@auth_stats_router.get("/me/stats/top-products", response_model=SellerTopProducts)
async def seller_top_products(seller_payload: dict = Depends(require_seller)):
    seller = await _seller_doc(seller_payload["seller_id"])
    return await seller_stats_service.get_seller_top_products(
        seller_payload["seller_id"],
        seller,
    )


router.include_router(stats_router)
router.include_router(auth_stats_router)
