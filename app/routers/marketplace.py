from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.marketplace import (
    MarketplaceCategoryProductsPublic,
    MarketplaceHomeFeedPublic,
    MarketplaceStorePublic,
)
from app.schemas.orders import CreateOrderRequest, OrderPublic
from app.schemas.popularity import ProductPopularityEventRequest
from app.services import marketplace as marketplace_service
from app.services import orders as orders_service
from app.services import product_popularity as popularity_service

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@router.get("/feed", response_model=MarketplaceHomeFeedPublic)
async def get_marketplace_home_feed(
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit_per_category: int = Query(20, ge=1, le=50),
):
    try:
        return await marketplace_service.list_home_feed(
            province_id.strip(),
            municipality_id.strip(),
            limit_per_category=limit_per_category,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/products", response_model=MarketplaceCategoryProductsPublic)
async def list_marketplace_category_products(
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    global_category_id: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    try:
        return await marketplace_service.list_category_products(
            province_id.strip(),
            municipality_id.strip(),
            global_category_id.strip(),
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/stores/{store_id}", response_model=MarketplaceStorePublic)
async def get_marketplace_store(store_id: str):
    try:
        return await marketplace_service.get_store_public(store_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/products/{product_id}/popularity", status_code=204)
async def record_product_popularity(product_id: str, payload: ProductPopularityEventRequest):
    try:
        await popularity_service.bump_product_popularity(product_id, payload.event)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/orders", response_model=OrderPublic, status_code=201)
async def create_marketplace_order(payload: CreateOrderRequest):
    try:
        return await orders_service.create_order(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
