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
    CatalogProductSearchPublic,
    CatalogSummaryPublic,
    CatalogThemePublic,
    CatalogThemeUpdate,
    CurrencyPublic,
)
from app.schemas.orders import CreateSellerManualOrderRequest, InvoiceType, OrderPublic, UpdateOrderRequest
from app.schemas.seller_profile import (
    CategoryPublic,
    SellerContactOtpConfirmRequest,
    SellerContactOtpResendRequest,
    SellerContactOtpStartResponse,
    SellerEmailUpdate,
    SellerPhoneUpdate,
    SellerProfileUpdate,
    SellerStoreNameUpdate,
    StoreBannerUpdate,
)
from app.schemas.seller_feedback import SellerFeedbackCreate, SellerFeedbackSubmitResult
from app.schemas.seller_stats import SellerProductsSoldChart, SellerRevenueChart, SellerStatsSummary, SellerTopProducts
from app.schemas.gestores import (
    GestorAllowedProductPublic,
    GestorCatalogAccess,
    GestorCatalogAccessUpdate,
    GestorCheckoutPhones,
    GestorCheckoutPhonesUpdate,
    GestorCreateRequest,
    GestorDeleteResult,
    GestorPublic,
)
from app.security import create_seller_token
from app.password_reset.schemas import (
    PasswordResetCompleteRequest,
    PasswordResetCompleteResponse,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetResendRequest,
    PasswordResetStartRequest,
    PasswordResetStartResponse,
)
from app.password_reset import service as password_reset_service
from app.services import auth as auth_service
from app.services import catalog as catalog_service
from app.services import catalog_theme_settings as catalog_theme_service
from app.services import gestores as gestores_service
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


@router.post("/password-reset/start", response_model=PasswordResetStartResponse)
async def start_password_reset(payload: PasswordResetStartRequest):
    return await password_reset_service.start_password_reset(
        method=payload.method,
        phone=payload.phone,
        store_name=payload.store_name,
    )


@router.post("/password-reset/otp/resimage.pngend", response_model=PasswordResetStartResponse)
async def resend_password_reset_otp(payload: PasswordResetResendRequest):
    return await password_reset_service.resend_password_reset_otp(
        challenge_id=payload.challenge_id,
        channel=payload.channel,
    )


@router.post("/password-reset/otp/confirm", response_model=PasswordResetConfirmResponse)
async def confirm_password_reset_otp(payload: PasswordResetConfirmRequest):
    return await password_reset_service.confirm_password_reset_otp(
        challenge_id=payload.challenge_id,
        email_code=payload.email_code,
        phone_code=payload.phone_code,
    )


@router.post("/password-reset/complete", response_model=PasswordResetCompleteResponse)
async def complete_password_reset(payload: PasswordResetCompleteRequest):
    return await password_reset_service.complete_password_reset(
        challenge_id=payload.challenge_id,
        password=payload.password,
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
    _payload: SellerPhoneUpdate,
    seller_payload: dict = Depends(require_seller),
):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Verifica el nuevo teléfono con el código SMS.",
    )


@router.post("/me/phone/otp/start", response_model=SellerContactOtpStartResponse)
async def start_seller_phone_otp(
    payload: SellerPhoneUpdate,
    seller_payload: dict = Depends(require_seller),
):
    from app.register.contact_changes import start_phone_change

    return await start_phone_change(
        seller_id=seller_payload["seller_id"],
        phone=payload.phone,
    )


@router.post("/me/email/otp/start", response_model=SellerContactOtpStartResponse)
async def start_seller_email_otp(
    payload: SellerEmailUpdate,
    seller_payload: dict = Depends(require_seller),
):
    from app.register.contact_changes import start_email_change

    return await start_email_change(
        seller_id=seller_payload["seller_id"],
        email=payload.email,
    )


@router.post("/me/contact-otp/resend", response_model=SellerContactOtpStartResponse)
async def resend_seller_contact_otp(
    payload: SellerContactOtpResendRequest,
    seller_payload: dict = Depends(require_seller),
):
    from app.register.contact_changes import resend_contact_change

    return await resend_contact_change(
        seller_id=seller_payload["seller_id"],
        challenge_id=payload.challenge_id,
    )


@router.post("/me/contact-otp/confirm", response_model=SellerPublic)
async def confirm_seller_contact_otp(
    payload: SellerContactOtpConfirmRequest,
    seller_payload: dict = Depends(require_seller),
):
    from app.register.contact_changes import confirm_contact_change

    return await confirm_contact_change(
        seller_id=seller_payload["seller_id"],
        challenge_id=payload.challenge_id,
        code=payload.code,
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


@router.post("/me/store-banners", response_model=SellerPublic, status_code=201)
async def upload_store_banner(
    photo: UploadFile = File(...),
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.add_store_banner(
        seller_payload["seller_id"],
        photo,
    )


@router.patch("/me/store-banners/{banner_id}", response_model=SellerPublic)
async def update_store_banner(
    banner_id: str,
    payload: StoreBannerUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.set_store_banner_active(
        seller_payload["seller_id"],
        banner_id,
        payload,
    )


@router.delete("/me/store-banners/{banner_id}", response_model=SellerPublic)
async def remove_store_banner(
    banner_id: str,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.delete_store_banner(
        seller_payload["seller_id"],
        banner_id,
    )


@router.get("/me/catalog", response_model=CatalogSummaryPublic)
async def get_my_catalog(seller_payload: dict = Depends(require_seller)):
    return await catalog_service.get_catalog_summary(seller_payload["seller_id"])


@router.get("/me/gestores", response_model=list[GestorPublic])
async def list_my_gestores(seller_payload: dict = Depends(require_seller)):
    return await gestores_service.list_seller_gestores(seller_payload["seller_id"])


@router.post("/me/gestores", response_model=GestorPublic, status_code=201)
async def create_my_gestor(
    payload: GestorCreateRequest,
    seller_payload: dict = Depends(require_seller),
):
    return await gestores_service.create_seller_gestor(
        seller_payload["seller_id"],
        payload.username,
    )


@router.get("/me/gestores/catalog-access", response_model=GestorCatalogAccess)
async def get_my_gestor_catalog_access(seller_payload: dict = Depends(require_seller)):
    return await gestores_service.get_seller_gestor_catalog_access(seller_payload["seller_id"])


@router.put("/me/gestores/catalog-access", response_model=GestorCatalogAccess)
async def update_my_gestor_catalog_access(
    payload: GestorCatalogAccessUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await gestores_service.update_seller_gestor_catalog_access(
        seller_payload["seller_id"],
        payload,
    )


@router.get("/me/gestores/checkout-phones", response_model=GestorCheckoutPhones)
async def get_my_gestor_checkout_phones(seller_payload: dict = Depends(require_seller)):
    return await gestores_service.get_seller_checkout_phones(seller_payload["seller_id"])


@router.put("/me/gestores/checkout-phones", response_model=GestorCheckoutPhones)
async def update_my_gestor_checkout_phones(
    payload: GestorCheckoutPhonesUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await gestores_service.update_seller_checkout_phones(
        seller_payload["seller_id"],
        payload,
    )


@router.get("/me/gestores/network-products", response_model=list[GestorAllowedProductPublic])
async def list_my_gestor_network_products(seller_payload: dict = Depends(require_seller)):
    return await gestores_service.list_allowed_products_for_seller_network(
        seller_payload["seller_id"]
    )


@router.delete("/me/gestores/{gestor_id}", response_model=GestorDeleteResult)
async def delete_my_gestor(
    gestor_id: str,
    seller_payload: dict = Depends(require_seller),
):
    return await gestores_service.delete_seller_gestor(
        seller_payload["seller_id"],
        gestor_id,
    )

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


@router.get("/me/catalog/products/search", response_model=CatalogProductSearchPublic)
async def search_my_catalog_products(
    q: str = Query(default=""),
    seller_payload: dict = Depends(require_seller),
):
    return await catalog_service.search_seller_ordered_products(seller_payload["seller_id"], q)


@router.post("/me/catalog/products", response_model=CatalogProductPublic, status_code=201)
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
        photos=photos,
        frontal_index=frontal_index,
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
    photos: list[UploadFile] | None = File(None),
    remove_image_ids: str | None = Form(None),
    frontal_image_id: str | None = Form(None),
    frontal_new_index: int | None = Form(None),
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
        photos=photos,
        remove_image_ids_raw=remove_image_ids,
        frontal_image_id=frontal_image_id,
        frontal_new_index=frontal_new_index,
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


@router.post("/me/orders", response_model=OrderPublic, status_code=201)
async def create_my_manual_order(
    payload: CreateSellerManualOrderRequest,
    seller_payload: dict = Depends(require_seller),
):
    try:
        return await orders_service.create_seller_manual_order(
            seller_payload["seller_id"],
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


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
