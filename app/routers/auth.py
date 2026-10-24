from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.auth.utils import require_seller
from app.auth.schemas import SellerPublic
from app.schemas.orders import CreateSellerManualOrderRequest, InvoiceType, OrderPublic, UpdateOrderRequest
from app.schemas.seller_profile import (
    CategoryPublic,
    SellerProfileUpdate,
    SellerStoreNameUpdate,
    StoreBannerUpdate,
)
from app.schemas.seller_feedback import SellerFeedbackCreate, SellerFeedbackSubmitResult
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
from app.services import gestores as gestores_service
from app.services import orders as orders_service
from app.services import seller_feedback as seller_feedback_service
from app.services import seller_profile as profile_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me/business-categories", response_model=list[CategoryPublic])
async def seller_business_categories(seller_payload: dict = Depends(require_seller)):
    return await profile_service.get_seller_business_categories(seller_payload["seller_id"])


@router.patch("/me/profile", response_model=SellerPublic)
async def update_seller_profile(
    payload: SellerProfileUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.update_seller_profile(seller_payload["seller_id"], payload)


@router.patch("/me/store-name", response_model=SellerPublic)
async def update_seller_store_name(
    payload: SellerStoreNameUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.update_seller_store_name(seller_payload["seller_id"], payload)


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
    return await profile_service.save_profile_photo(seller_payload["seller_id"], photo)


@router.post("/me/store-banners", response_model=SellerPublic, status_code=201)
async def upload_store_banner(
    photo: UploadFile = File(...),
    seller_payload: dict = Depends(require_seller),
):
    return await profile_service.add_store_banner(seller_payload["seller_id"], photo)


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
