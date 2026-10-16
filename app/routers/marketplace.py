from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.banners import BannerPublic
from app.schemas.marketplace import (
    JabaSyncPublic,
    JabaSyncRequest,
    MarketplaceBusinessesPublic,
    MarketplaceCategoryProductsPublic,
    MarketplaceGestorStoreCatalogPublic,
    MarketplaceGestorStoreCategoryProductsPublic,
    MarketplaceAvailabilityHintsPublic,
    MarketplaceHomeFeedPublic,
    MarketplaceProductPublic,
    MarketplaceSearchPublic,
    MarketplaceSharedProductsPublic,
    MarketplaceStoreCatalogPublic,
    MarketplaceStoreCategoryProductsPublic,
    MarketplaceStorePublic,
)
from app.schemas.orders import CreateOrderRequest, OrderPublic
from app.schemas.popularity import ProductPopularityEventRequest
from app.services import banners as banners_service
from app.services import marketplace as marketplace_service
from app.services import orders as orders_service
from app.services import product_popularity as popularity_service
from app.services import seller_stats as seller_stats_service

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@router.get("/banners", response_model=list[BannerPublic])
async def list_marketplace_banners(province_id: str | None = Query(default=None)):
    return await banners_service.list_public_banners(province_id=province_id)


@router.get("/feed", response_model=MarketplaceHomeFeedPublic)
async def get_marketplace_home_feed(
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit_per_category: int = Query(20, ge=1, le=50),
    limit: int = Query(4, ge=1, le=50),
    offset: int = Query(0, ge=0),
    municipios_adicionales: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.list_home_feed(
            province_id.strip(),
            municipality_id.strip(),
            limit_per_category=limit_per_category,
            section_limit=limit,
            section_offset=offset,
            municipios_adicionales=municipios_adicionales,
            currency=currency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/availability-hints", response_model=MarketplaceAvailabilityHintsPublic)
async def get_marketplace_availability_hints(
    province_id: str = Query(..., min_length=1),
    municipality_id: list[str] = Query(..., min_length=1),
    currency: str | None = Query(default=None),
    global_category_id: str | None = Query(default=None),
):
    try:
        return await marketplace_service.list_availability_hints(
            province_id.strip(),
            municipality_id,
            currency=currency,
            category_id=global_category_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/businesses", response_model=MarketplaceBusinessesPublic)
async def list_marketplace_businesses(
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    q: str = Query(default=""),
    category_id: str | None = Query(default=None),
    municipios_adicionales: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.list_businesses(
            province_id.strip(),
            municipality_id.strip(),
            limit=limit,
            offset=offset,
            query=q,
            category_id=category_id,
            municipios_adicionales=municipios_adicionales,
            currency=currency,
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
    municipios_adicionales: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.list_category_products(
            province_id.strip(),
            municipality_id.strip(),
            global_category_id.strip(),
            limit=limit,
            offset=offset,
            municipios_adicionales=municipios_adicionales,
            currency=currency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/products/{product_id}", response_model=MarketplaceProductPublic)
async def get_marketplace_product(
    product_id: str,
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
):
    try:
        return await marketplace_service.get_marketplace_product(
            product_id,
            province_id.strip(),
            municipality_id.strip(),
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if detail == "Producto no encontrado."
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from exc


@router.get("/shared-products", response_model=MarketplaceSharedProductsPublic)
async def get_shared_products(
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    item: list[str] | None = Query(default=None),
):
    try:
        return await marketplace_service.list_shared_products(
            province_id.strip(),
            municipality_id.strip(),
            item or [],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/search", response_model=MarketplaceSearchPublic)
async def search_marketplace_products(
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    q: str = Query(default=""),
    global_category_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    municipios_adicionales: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
    store_slug: str | None = Query(default=None),
    gestor_username: str | None = Query(default=None),
):
    try:
        return await marketplace_service.search_products(
            province_id.strip(),
            municipality_id.strip(),
            query=q,
            global_category_id=global_category_id,
            limit=limit,
            offset=offset,
            municipios_adicionales=municipios_adicionales,
            currency=currency,
            store_slug=store_slug,
            gestor_username=gestor_username,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/stores/{store_slug}/view", status_code=status.HTTP_204_NO_CONTENT)
async def record_marketplace_store_view(
    store_slug: str,
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
):
    try:
        seller_id = await marketplace_service.resolve_visible_seller_id(
            store_slug,
            province_id.strip(),
            municipality_id.strip(),
        )
        await seller_stats_service.record_profile_view(seller_id)
    except ValueError:
        return None
    return None


@router.get("/stores/{store_slug}/catalog", response_model=MarketplaceStoreCatalogPublic)
async def get_marketplace_store_catalog(
    store_slug: str,
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit_per_category: int = Query(20, ge=1, le=50),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.get_store_catalog(
            store_slug,
            province_id.strip(),
            municipality_id.strip(),
            limit_per_category=limit_per_category,
            currency=currency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/stores/{store_slug}/gestores/{gestor_username}/catalog",
    response_model=MarketplaceGestorStoreCatalogPublic,
)
async def get_marketplace_gestor_store_catalog(
    store_slug: str,
    gestor_username: str,
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit_per_category: int = Query(20, ge=1, le=50),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.get_gestor_store_catalog(
            store_slug,
            gestor_username.strip(),
            province_id.strip(),
            municipality_id.strip(),
            limit_per_category=limit_per_category,
            currency=currency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/stores/{store_slug}/categories/{category_id}/products",
    response_model=MarketplaceStoreCategoryProductsPublic,
)
async def list_marketplace_store_category_products(
    store_slug: str,
    category_id: str,
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.list_store_category_products(
            store_slug,
            province_id.strip(),
            municipality_id.strip(),
            category_id.strip(),
            limit=limit,
            offset=offset,
            currency=currency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/stores/{store_slug}/gestores/{gestor_username}/categories/{category_id}/products",
    response_model=MarketplaceGestorStoreCategoryProductsPublic,
)
async def list_marketplace_gestor_store_category_products(
    store_slug: str,
    gestor_username: str,
    category_id: str,
    province_id: str = Query(..., min_length=1),
    municipality_id: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    currency: str | None = Query(default=None),
):
    try:
        return await marketplace_service.list_gestor_store_category_products(
            store_slug,
            gestor_username.strip(),
            province_id.strip(),
            municipality_id.strip(),
            category_id.strip(),
            limit=limit,
            offset=offset,
            currency=currency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/stores/{store_slug}", response_model=MarketplaceStorePublic)
async def get_marketplace_store(store_slug: str):
    try:
        return await marketplace_service.get_store_public(store_slug)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/jaba/sync", response_model=JabaSyncPublic)
async def sync_marketplace_jaba(payload: JabaSyncRequest):
    try:
        return await marketplace_service.sync_jaba_products(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
