from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.auth.utils import require_customer, require_seller
from app.orders import service as orders_service

from . import services
from .schema import (
    CustomerAddressRequest,
    CustomerContactOtpConfirmRequest,
    CustomerContactOtpStartResponse,
    CustomerEmailUpdateRequest,
    CustomerIdentityCardUpdateRequest,
    CustomerLoginRequest,
    CustomerLoginResponse,
    CustomerOtpConfirmRequest,
    CustomerOtpResendRequest,
    CustomerOtpStartResponse,
    CustomerPasswordResetCompleteRequest,
    CustomerPasswordResetCompleteResponse,
    CustomerPasswordResetConfirmRequest,
    CustomerPasswordResetConfirmResponse,
    CustomerPasswordResetResendRequest,
    CustomerPasswordResetStartRequest,
    CustomerPasswordResetStartResponse,
    CustomerPhoneUpdateRequest,
    CustomerPublic,
    CustomerRegisterRequest,
)

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.post("/register/otp/start", response_model=CustomerOtpStartResponse)
async def start_customer_registration(payload: CustomerRegisterRequest):
    return await services.start_customer_registration(payload)


@router.post("/register/otp/resend", response_model=CustomerOtpStartResponse)
async def resend_customer_registration(payload: CustomerOtpResendRequest):
    return await services.resend_customer_registration(payload)


@router.post("/register/otp/confirm", response_model=CustomerLoginResponse, status_code=201)
async def confirm_customer_registration(payload: CustomerOtpConfirmRequest):
    return await services.confirm_customer_registration(payload)


@router.post("/login", response_model=CustomerLoginResponse)
async def customer_login(payload: CustomerLoginRequest):
    return await services.customer_login(payload)


@router.get("/me", response_model=CustomerPublic)
async def get_my_customer(customer_payload: dict = Depends(require_customer)):
    return await services.get_customer(customer_payload["customer_id"])


@router.patch("/me", response_model=CustomerPublic)
async def update_my_customer(payload: dict[str, Any], customer_payload: dict = Depends(require_customer)):
    return await services.update_customer(customer_payload["customer_id"], payload)


@router.post("/me/email/otp/start", response_model=CustomerContactOtpStartResponse)
async def start_customer_email_change(
    payload: CustomerEmailUpdateRequest,
    customer_payload: dict = Depends(require_customer),
):
    return await services.start_customer_contact_change(
        customer_id=customer_payload["customer_id"], kind="email", value=payload.email
    )


@router.post("/me/phone/otp/start", response_model=CustomerContactOtpStartResponse)
async def start_customer_phone_change(
    payload: CustomerPhoneUpdateRequest,
    customer_payload: dict = Depends(require_customer),
):
    return await services.start_customer_contact_change(
        customer_id=customer_payload["customer_id"], kind="phone", value=payload.phone
    )


@router.post("/me/contact-otp/confirm", response_model=CustomerPublic)
async def confirm_customer_contact_change(
    payload: CustomerContactOtpConfirmRequest,
    customer_payload: dict = Depends(require_customer),
):
    return await services.confirm_customer_contact_change(payload, customer_payload["customer_id"])


@router.patch("/me/identity-card", response_model=CustomerPublic)
async def update_customer_identity_card(
    payload: CustomerIdentityCardUpdateRequest,
    customer_payload: dict = Depends(require_customer),
):
    return await services.update_customer_identity_card(payload, customer_payload["customer_id"])


@router.post("/password-reset/start", response_model=CustomerPasswordResetStartResponse)
async def start_customer_password_reset(payload: CustomerPasswordResetStartRequest):
    return await services.start_customer_password_reset(payload)


@router.post("/password-reset/otp/resend", response_model=CustomerPasswordResetStartResponse)
async def resend_customer_password_reset(payload: CustomerPasswordResetResendRequest):
    return await services.resend_customer_password_reset(payload)


@router.post("/password-reset/otp/confirm", response_model=CustomerPasswordResetConfirmResponse)
async def confirm_customer_password_reset(payload: CustomerPasswordResetConfirmRequest):
    return await services.confirm_customer_password_reset(payload)


@router.post("/password-reset/complete", response_model=CustomerPasswordResetCompleteResponse)
async def complete_customer_password_reset(payload: CustomerPasswordResetCompleteRequest):
    return await services.complete_customer_password_reset(payload)


@router.post("/me/profile-photo", response_model=CustomerPublic)
async def upload_customer_photo(
    photo: UploadFile = File(...),
    customer_payload: dict = Depends(require_customer),
):
    return await services.upload_customer_photo(photo, customer_payload["customer_id"])


@router.post("/me/addresses", response_model=CustomerPublic)
async def add_customer_address(
    payload: CustomerAddressRequest,
    customer_payload: dict = Depends(require_customer),
):
    return await services.add_customer_address(payload, customer_payload["customer_id"])


@router.put("/me/addresses/{address_id}", response_model=CustomerPublic)
async def update_customer_address(
    address_id: str,
    payload: CustomerAddressRequest,
    customer_payload: dict = Depends(require_customer),
):
    return await services.update_customer_address(address_id, payload, customer_payload["customer_id"])


@router.delete("/me/addresses/{address_id}", response_model=CustomerPublic)
async def delete_customer_address(
    address_id: str,
    customer_payload: dict = Depends(require_customer),
):
    return await services.delete_customer_address(address_id, customer_payload["customer_id"])


@router.put("/me/favorites/{product_id}", response_model=CustomerPublic)
async def add_customer_favorite(product_id: str, customer_payload: dict = Depends(require_customer)):
    return await services.add_customer_favorite(product_id, customer_payload["customer_id"])


@router.delete("/me/favorites/{product_id}", response_model=CustomerPublic)
async def remove_customer_favorite(product_id: str, customer_payload: dict = Depends(require_customer)):
    return await services.remove_customer_favorite(product_id, customer_payload["customer_id"])


@router.get("/me/orders")
async def list_customer_orders(customer_payload: dict = Depends(require_customer)):
    return await services.list_customer_orders(customer_payload["customer_id"])


@router.get("/me/orders/{order_id}/agreements/{kind}.pdf")
async def download_customer_order_agreement(
    order_id: str,
    kind: Literal["terms", "delivery_policy"],
    customer_payload: dict = Depends(require_customer),
):
    try:
        pdf_bytes, filename = await orders_service.generate_customer_order_agreement_pdf(
            customer_payload["customer_id"],
            order_id,
            kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/me/orders/{order_id}/evidence.pdf")
async def download_customer_order_evidence(
    order_id: str,
    customer_payload: dict = Depends(require_customer),
):
    try:
        pdf_bytes, filename = await orders_service.generate_customer_order_evidence_pdf(
            customer_payload["customer_id"],
            order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/store/customers")
async def list_store_customers(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    orders_limit: int = Query(default=10, ge=1, le=50),
    customer_id: str | None = Query(default=None),
    orders_offset: int = Query(default=0, ge=0),
    search: str = Query(default="", max_length=200),
    location: str = Query(default="", max_length=200),
    currency: str = Query(default="", max_length=8),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    products: list[str] = Query(default=[]),
    seller_payload: dict = Depends(require_seller),
):
    return await services.list_store_customers(
        seller_payload["seller_id"],
        offset=offset,
        limit=limit,
        orders_limit=orders_limit,
        customer_id=customer_id,
        orders_offset=orders_offset,
        search=search,
        location=location,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
        products=products,
    )
