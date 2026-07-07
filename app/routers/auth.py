from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.dependencies import require_seller
from app.schemas.auth import SellerLoginRequest, SellerLoginResponse, SellerPublic, SubscriptionExpiredPublic
from app.schemas.catalog import (
    CatalogCategoryCreate,
    CatalogCategoryProductSortUpdate,
    CatalogCategoryPublic,
    CatalogCategoryReorder,
    CatalogProductPublic,
    CatalogProductReorder,
    CatalogSummaryPublic,
    CatalogThemePublic,
    CatalogThemeUpdate,
    CurrencyPublic,
)
from app.schemas.notifications import SellerNotificationPublic, SellerNotificationUnreadCount, SellerNotificationBulkReadResult
from app.schemas.orders import InvoiceType, OrderPublic, UpdateOrderRequest
from app.schemas.seller_profile import (
    CategoryPublic,
    SellerPhoneUpdate,
    SellerProfileUpdate,
    SellerStoreNameUpdate,
)
from app.schemas.seller_feedback import SellerFeedbackCreate, SellerFeedbackSubmitResult
from app.schemas.seller_stats import SellerProductsSoldChart, SellerRevenueChart, SellerStatsSummary, SellerTopProducts
from app.security import create_seller_token
from app.services import auth as auth_service
from app.services import catalog as catalog_service
from app.services import catalog_theme_settings as catalog_theme_service
from app.services import notifications as notification_service
from app.services import orders as orders_service
from app.services import seller_feedback as seller_feedback_service
from app.services import seller_profile as profile_service
from app.services import seller_stats as seller_stats_service
from app.services.seller_stats import Granularity

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SellerLoginResponse)
async def seller_login(payload: SellerLoginRequest):
    result = await auth_service.login_seller(
        method=payload.method,
        password=payload.password,
        phone=payload.phone,
        store_name=payload.store_name,
    )
    if isinstance(result, SubscriptionExpiredPublic):
        return SellerLoginResponse(subscription_expired=result)

    seller = profile_service.document_to_seller(result)
    return SellerLoginResponse(
        access_token=create_seller_token(
            seller_id=seller.id,
            store_name=seller.store_name,
        ),
        seller=seller,
    )


@router.get("/me", response_model=SellerPublic)
async def seller_me(seller_payload: dict = Depends(require_seller)):
    return await profile_service.get_seller_public(seller_payload["seller_id"])


@router.get("/me/business-categories", response_model=list[CategoryPublic])
async def seller_business_categories(seller_payload: dict = Depends(require_seller)):
    return await profile_service.get_seller_business_categories(seller_payload["seller_id"])


@router.patch("/me/profile", response_model=SellerPublic)
async def update_seller_profile(
    payload: SellerProfileUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.update_seller_profile(
        seller_payload["seller_id"],
        payload,
    )


@router.patch("/me/phone", response_model=SellerPublic)
async def update_seller_phone(
    payload: SellerPhoneUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.update_seller_phone(
        seller_payload["seller_id"],
        payload,
    )


@router.patch("/me/store-name", response_model=SellerPublic)
async def update_seller_store_name(
    payload: SellerStoreNameUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.update_seller_store_name(
        seller_payload["seller_id"],
        payload,
    )


@router.post("/me/feedback", response_model=SellerFeedbackSubmitResult, status_code=201)
async def submit_seller_feedback(
    payload: SellerFeedbackCreate,
    seller_payload: dict = Depends(require_seller),
):
    return await seller_feedback_service.submit_seller_feedback(
        seller_payload["seller_id"],
        payload,
    )


@router.post("/me/profile-photo", response_model=SellerPublic)
async def upload_profile_photo(
    photo: UploadFile = File(...),
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.save_profile_photo(
        seller_payload["seller_id"],
        photo,
    )


@router.get("/me/notifications", response_model=list[SellerNotificationPublic])
async def list_my_notifications(seller_payload: dict = Depends(require_seller)):
    return await notification_service.list_seller_notifications(seller_payload["seller_id"])


@router.get("/me/notifications/unread-count", response_model=SellerNotificationUnreadCount)
async def my_notifications_unread_count(seller_payload: dict = Depends(require_seller)):
    return await notification_service.get_unread_count(seller_payload["seller_id"])


@router.patch("/me/notifications/read-system", response_model=SellerNotificationBulkReadResult)
async def mark_my_system_notifications_read(seller_payload: dict = Depends(require_seller)):
    return await notification_service.mark_system_notifications_read(
        seller_payload["seller_id"],
    )


@router.patch("/me/notifications/{notification_id}/read", response_model=SellerNotificationPublic)
async def mark_my_notification_read(
    notification_id: str,
    seller_payload: dict = Depends(require_seller),
):
    return await notification_service.mark_notification_read(
        seller_payload["seller_id"],
        notification_id,
    )


@router.get("/me/catalog", response_model=CatalogSummaryPublic)
async def get_my_catalog(seller_payload: dict = Depends(require_seller)):
    return await catalog_service.get_catalog_summary(seller_payload["seller_id"])


@router.post("/me/catalog/categories", response_model=CatalogCategoryPublic, status_code=201)
async def create_my_catalog_category(
    payload: CatalogCategoryCreate,
    seller_payload: dict = Depends(require_seller),
):
    return await catalog_service.create_catalog_category(
        seller_payload["seller_id"],
        payload,
    )


@router.delete("/me/catalog/categories/{category_id}", status_code=204)
async def delete_my_catalog_category(
    category_id: str,
    seller_payload: dict = Depends(require_seller),
):
    await catalog_service.delete_catalog_category(
        seller_payload["seller_id"],
        category_id,
    )


@router.put("/me/catalog/categories/order", response_model=CatalogSummaryPublic)
async def reorder_my_catalog_categories(
    payload: CatalogCategoryReorder,
    seller_payload: dict = Depends(require_seller),
):
    return await catalog_service.reorder_catalog_categories(
        seller_payload["seller_id"],
        payload,
    )


@router.patch("/me/catalog/categories/{category_id}/product-sort", response_model=CatalogSummaryPublic)
async def update_my_catalog_category_product_sort(
    category_id: str,
    payload: CatalogCategoryProductSortUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await catalog_service.update_category_product_sort_mode(
        seller_payload["seller_id"],
        category_id,
        payload,
    )


@router.put(
    "/me/catalog/categories/{category_id}/products/order",
    response_model=CatalogSummaryPublic,
)
async def reorder_my_catalog_products(
    category_id: str,
    payload: CatalogProductReorder,
    seller_payload: dict = Depends(require_seller),
):
    return await catalog_service.reorder_catalog_products(
        seller_payload["seller_id"],
        category_id,
        payload,
    )


@router.patch("/me/catalog/theme", response_model=CatalogThemePublic)
async def update_my_catalog_theme(
    payload: CatalogThemeUpdate,
    seller_payload: dict = Depends(require_seller),
):
    theme = await catalog_theme_service.update_seller_catalog_theme(
        seller_payload["seller_id"],
        payload.catalog_theme,
    )
    return CatalogThemePublic(catalog_theme=theme)


@router.get("/me/catalog/currencies", response_model=list[CurrencyPublic])
async def get_my_catalog_currencies(_seller_payload: dict = Depends(require_seller)):
    return catalog_service.get_supported_currencies()


@router.post("/me/catalog/products", response_model=CatalogProductPublic, status_code=201)
async def create_my_catalog_product(
    name: str = Form(...),
    category_id: str = Form(...),
    global_category_id: str = Form(...),
    base_price: float = Form(...),
    base_currency: str = Form(...),
    offers_delivery: bool = Form(...),
    photo: UploadFile = File(...),
    seller_payload: dict = Depends(require_seller),
    description: str | None = Form(None),
    accepted_currencies: str = Form("[]"),
    view_only: bool = Form(False),
    is_available: bool = Form(True),
):
    return await catalog_service.create_catalog_product(
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
    )


@router.patch("/me/catalog/products/{product_id}", response_model=CatalogProductPublic)
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
):
    return await catalog_service.update_catalog_product(
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
    )


@router.delete("/me/catalog/products/{product_id}", status_code=204)
async def delete_my_catalog_product(
    product_id: str,
    seller_payload: dict = Depends(require_seller),
):
    await catalog_service.delete_catalog_product(
        seller_payload["seller_id"],
        product_id,
    )


@router.get("/me/orders", response_model=list[OrderPublic])
async def list_my_orders(seller_payload: dict = Depends(require_seller)):
    return await orders_service.list_seller_orders(seller_payload["seller_id"])


@router.patch("/me/orders/{order_id}", response_model=OrderPublic)
async def update_my_order(
    order_id: str,
    payload: UpdateOrderRequest,
    seller_payload: dict = Depends(require_seller),
):
    try:
        return await orders_service.update_seller_order(
            seller_payload["seller_id"],
            order_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("/me/orders/{order_id}", status_code=204)
async def delete_my_order(
    order_id: str,
    seller_payload: dict = Depends(require_seller),
):
    try:
        await orders_service.delete_seller_order(
            seller_payload["seller_id"],
            order_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/me/stats/summary", response_model=SellerStatsSummary)
async def seller_stats_summary(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    seller_payload: dict = Depends(require_seller),
):
    from app.database import get_registrations_collection
    from bson import ObjectId

    seller = await get_registrations_collection().find_one(
        {"_id": ObjectId(seller_payload["seller_id"])},
    )
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )

    return await seller_stats_service.get_seller_stats_summary(
        seller_payload["seller_id"],
        seller,
        year=year,
        month=month,
    )


@router.get("/me/stats/revenue", response_model=SellerRevenueChart)
async def seller_revenue_chart(
    granularity: Granularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    seller_payload: dict = Depends(require_seller),
):
    from app.database import get_registrations_collection
    from bson import ObjectId

    seller = await get_registrations_collection().find_one(
        {"_id": ObjectId(seller_payload["seller_id"])},
    )
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )

    return await seller_stats_service.get_seller_revenue_chart(
        seller_payload["seller_id"],
        seller,
        granularity=granularity,
        year=year,
        month=month,
    )


@router.get("/me/stats/products-sold", response_model=SellerProductsSoldChart)
async def seller_products_sold_chart(
    granularity: Granularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    seller_payload: dict = Depends(require_seller),
):
    from app.database import get_registrations_collection
    from bson import ObjectId

    seller = await get_registrations_collection().find_one(
        {"_id": ObjectId(seller_payload["seller_id"])},
    )
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )

    return await seller_stats_service.get_seller_products_sold_chart(
        seller_payload["seller_id"],
        seller,
        granularity=granularity,
        year=year,
        month=month,
    )


@router.get("/me/stats/top-products", response_model=SellerTopProducts)
async def seller_top_products(
    seller_payload: dict = Depends(require_seller),
):
    from app.database import get_registrations_collection
    from bson import ObjectId

    seller = await get_registrations_collection().find_one(
        {"_id": ObjectId(seller_payload["seller_id"])},
    )
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )

    return await seller_stats_service.get_seller_top_products(
        seller_payload["seller_id"],
        seller,
    )


@router.get("/me/orders/{order_id}/invoice.pdf")
async def download_my_order_invoice(
    order_id: str,
    type: InvoiceType = Query("store"),
    seller_payload: dict = Depends(require_seller),
):
    try:
        pdf_bytes, filename = await orders_service.generate_order_invoice_pdf(
            seller_payload["seller_id"],
            order_id,
            type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
