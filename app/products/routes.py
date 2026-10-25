from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.auth.utils import require_admin, require_seller
from app.products.schemas import (
    AdminProductList,
    CatalogCategoryCreate,
    CatalogCategoryProductSortUpdate,
    CatalogCategoryPublic,
    CatalogCategoryReorder,
    CatalogProductPublic,
    CatalogProductReorder,
    CatalogProductSearchPublic,
    CatalogSummaryPublic,
    CatalogThemePublic,
    CatalogThemeUpdate,
    CurrencyPublic,
)
from app.products import service as products_service
from app.services import catalog_theme_settings as catalog_theme_service

router = APIRouter()

seller_router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@seller_router.get("/me/catalog", response_model=CatalogSummaryPublic)
async def get_my_catalog(seller_payload: dict = Depends(require_seller)):
    return await products_service.get_catalog_summary(seller_payload["seller_id"])


@seller_router.post("/me/catalog/categories", response_model=CatalogCategoryPublic, status_code=201)
async def create_my_catalog_category(
    payload: CatalogCategoryCreate,
    seller_payload: dict = Depends(require_seller),
):
    return await products_service.create_catalog_category(
        seller_payload["seller_id"],
        payload,
    )


@seller_router.delete("/me/catalog/categories/{category_id}", status_code=204)
async def delete_my_catalog_category(
    category_id: str,
    seller_payload: dict = Depends(require_seller),
):
    await products_service.delete_catalog_category(
        seller_payload["seller_id"],
        category_id,
    )


@seller_router.put("/me/catalog/categories/order", response_model=CatalogSummaryPublic)
async def reorder_my_catalog_categories(
    payload: CatalogCategoryReorder,
    seller_payload: dict = Depends(require_seller),
):
    return await products_service.reorder_catalog_categories(
        seller_payload["seller_id"],
        payload,
    )


@seller_router.patch(
    "/me/catalog/categories/{category_id}/product-sort",
    response_model=CatalogSummaryPublic,
)
async def update_my_catalog_category_product_sort(
    category_id: str,
    payload: CatalogCategoryProductSortUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await products_service.update_category_product_sort_mode(
        seller_payload["seller_id"],
        category_id,
        payload,
    )


@seller_router.put(
    "/me/catalog/categories/{category_id}/products/order",
    response_model=CatalogSummaryPublic,
)
async def reorder_my_catalog_products(
    category_id: str,
    payload: CatalogProductReorder,
    seller_payload: dict = Depends(require_seller),
):
    return await products_service.reorder_catalog_products(
        seller_payload["seller_id"],
        category_id,
        payload,
    )


@seller_router.patch("/me/catalog/theme", response_model=CatalogThemePublic)
async def update_my_catalog_theme(
    payload: CatalogThemeUpdate,
    seller_payload: dict = Depends(require_seller),
):
    saved = await catalog_theme_service.update_seller_catalog_theme(
        seller_payload["seller_id"],
        payload.catalog_theme,
        payload.catalog_palette.model_dump() if payload.catalog_palette else None,
    )
    return CatalogThemePublic(
        catalog_theme=saved["catalog_theme"],
        catalog_palette=saved["catalog_palette"],
    )


@seller_router.get("/me/catalog/currencies", response_model=list[CurrencyPublic])
async def get_my_catalog_currencies(_seller_payload: dict = Depends(require_seller)):
    return products_service.get_supported_currencies()


@seller_router.get("/me/catalog/products/search", response_model=CatalogProductSearchPublic)
async def search_my_catalog_products(
    q: str = Query(default=""),
    seller_payload: dict = Depends(require_seller),
):
    return await products_service.search_seller_ordered_products(seller_payload["seller_id"], q)


@seller_router.post("/me/catalog/products", response_model=CatalogProductPublic, status_code=201)
async def create_my_catalog_product(
    name: str = Form(...),
    category_id: str = Form(...),
    global_category_id: str = Form(...),
    base_price: float = Form(...),
    base_currency: str = Form(...),
    offers_delivery: bool = Form(...),
    seller_payload: dict = Depends(require_seller),
    description: str | None = Form(None),
    accepted_currencies: str = Form("[]"),
    view_only: bool = Form(False),
    is_available: bool = Form(True),
    photo: UploadFile | None = File(None),
    photos: list[UploadFile] | None = File(None),
    frontal_index: int = Form(0),
    discount_percent: str | None = Form(None),
    sales_areas: str | None = Form(None),
):
    return await products_service.create_catalog_product(
        seller_payload["seller_id"],
        name=name,
        description=description,
        base_price=base_price,
        base_currency=base_currency,
        accepted_currencies_raw=accepted_currencies,
        category_id=category_id,
        global_category_id=global_category_id,
        offers_delivery=offers_delivery,
        view_only=view_only,
        is_available=is_available,
        photo=photo,
        photos=photos,
        frontal_index=frontal_index,
        discount_percent=discount_percent,
        sales_areas_raw=sales_areas,
    )


@seller_router.patch("/me/catalog/products/{product_id}", response_model=CatalogProductPublic)
async def update_my_catalog_product(
    product_id: str,
    name: str = Form(...),
    category_id: str = Form(...),
    global_category_id: str = Form(...),
    base_price: float = Form(...),
    base_currency: str = Form(...),
    offers_delivery: bool = Form(...),
    seller_payload: dict = Depends(require_seller),
    description: str | None = Form(None),
    accepted_currencies: str = Form("[]"),
    view_only: bool = Form(False),
    is_available: bool = Form(True),
    photo: UploadFile | None = File(None),
    photos: list[UploadFile] | None = File(None),
    remove_image_ids: str | None = Form(None),
    frontal_image_id: str | None = Form(None),
    frontal_new_index: int | None = Form(None),
    discount_percent: str | None = Form(None),
    sales_areas: str | None = Form(None),
):
    return await products_service.update_catalog_product(
        seller_payload["seller_id"],
        product_id,
        name=name,
        description=description,
        base_price=base_price,
        base_currency=base_currency,
        accepted_currencies_raw=accepted_currencies,
        category_id=category_id,
        global_category_id=global_category_id,
        offers_delivery=offers_delivery,
        view_only=view_only,
        is_available=is_available,
        photo=photo,
        photos=photos,
        remove_image_ids_raw=remove_image_ids,
        frontal_image_id=frontal_image_id,
        frontal_new_index=frontal_new_index,
        discount_percent=discount_percent,
        sales_areas_raw=sales_areas,
    )


@seller_router.delete("/me/catalog/products/{product_id}", status_code=204)
async def delete_my_catalog_product(
    product_id: str,
    seller_payload: dict = Depends(require_seller),
):
    await products_service.delete_catalog_product(
        seller_payload["seller_id"],
        product_id,
    )


@admin_router.get("/products", response_model=AdminProductList)
async def list_products(_: dict = Depends(require_admin)):
    return await products_service.list_admin_products()


router.include_router(seller_router)
router.include_router(admin_router)
