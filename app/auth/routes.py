from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.contact_changes import (
    confirm_contact_change,
    resend_contact_change,
    start_email_change,
    start_phone_change,
)
from app.auth.schemas import (
    PasswordResetCompleteRequest,
    PasswordResetCompleteResponse,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetResendRequest,
    PasswordResetStartRequest,
    PasswordResetStartResponse,
    RegisterOtpConfirmRequest,
    RegisterOtpConfirmResponse,
    RegisterOtpResendRequest,
    RegisterOtpStartResponse,
    RegisterRequest,
    RegisterResponse,
    SellerLoginRequest,
    SellerLoginResponse,
    SellerPublic,
    SubscriptionExpiredPublic,
)
from app.auth import service as auth_service
from app.auth.utils import create_seller_token, require_seller
from app.schemas.seller_profile import (
    SellerContactOtpConfirmRequest,
    SellerContactOtpResendRequest,
    SellerContactOtpStartResponse,
    SellerEmailUpdate,
    SellerPhoneUpdate,
)
from app.services import seller_profile as profile_service

router = APIRouter()

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
register_router = APIRouter(prefix="/api/register", tags=["register"])


@auth_router.post("/login", response_model=SellerLoginResponse)
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


@auth_router.post("/password-reset/start", response_model=PasswordResetStartResponse)
async def start_password_reset(payload: PasswordResetStartRequest):
    return await auth_service.start_password_reset(
        method=payload.method,
        phone=payload.phone,
        store_name=payload.store_name,
    )


@auth_router.post("/password-reset/otp/resend", response_model=PasswordResetStartResponse)
async def resend_password_reset_otp(payload: PasswordResetResendRequest):
    return await auth_service.resend_password_reset_otp(
        challenge_id=payload.challenge_id,
        channel=payload.channel,
    )


@auth_router.post("/password-reset/otp/confirm", response_model=PasswordResetConfirmResponse)
async def confirm_password_reset_otp(payload: PasswordResetConfirmRequest):
    return await auth_service.confirm_password_reset_otp(
        challenge_id=payload.challenge_id,
        email_code=payload.email_code,
        phone_code=payload.phone_code,
    )


@auth_router.post("/password-reset/complete", response_model=PasswordResetCompleteResponse)
async def complete_password_reset(payload: PasswordResetCompleteRequest):
    return await auth_service.complete_password_reset(
        challenge_id=payload.challenge_id,
        password=payload.password,
    )


@auth_router.get("/me", response_model=SellerPublic)
async def seller_me(seller_payload: dict = Depends(require_seller)):
    return await profile_service.get_seller_public(seller_payload["seller_id"])


@auth_router.patch("/me/phone", response_model=SellerPublic)
async def update_seller_phone(
    _payload: SellerPhoneUpdate,
    seller_payload: dict = Depends(require_seller),
):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Verifica el nuevo teléfono con el código SMS.",
    )


@auth_router.post("/me/phone/otp/start", response_model=SellerContactOtpStartResponse)
async def start_seller_phone_otp(
    payload: SellerPhoneUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await start_phone_change(
        seller_id=seller_payload["seller_id"],
        phone=payload.phone,
    )


@auth_router.post("/me/email/otp/start", response_model=SellerContactOtpStartResponse)
async def start_seller_email_otp(
    payload: SellerEmailUpdate,
    seller_payload: dict = Depends(require_seller),
):
    return await start_email_change(
        seller_id=seller_payload["seller_id"],
        email=payload.email,
    )


@auth_router.post("/me/contact-otp/resend", response_model=SellerContactOtpStartResponse)
async def resend_seller_contact_otp(
    payload: SellerContactOtpResendRequest,
    seller_payload: dict = Depends(require_seller),
):
    return await resend_contact_change(
        seller_id=seller_payload["seller_id"],
        challenge_id=payload.challenge_id,
    )


@auth_router.post("/me/contact-otp/confirm", response_model=SellerPublic)
async def confirm_seller_contact_otp(
    payload: SellerContactOtpConfirmRequest,
    seller_payload: dict = Depends(require_seller),
):
    return await confirm_contact_change(
        seller_id=seller_payload["seller_id"],
        challenge_id=payload.challenge_id,
        code=payload.code,
    )


@register_router.post("", response_model=RegisterResponse, status_code=201)
async def register_seller(_payload: RegisterRequest):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Verifica tu correo y teléfono para crear la tienda.",
    )


@register_router.post("/otp/start", response_model=RegisterOtpStartResponse)
async def start_otp(payload: RegisterRequest):
    return await auth_service.start_registration_otp(payload)


@register_router.post("/otp/resend", response_model=RegisterOtpStartResponse)
async def resend_otp(payload: RegisterOtpResendRequest):
    return await auth_service.resend_registration_otp(
        challenge_id=payload.challenge_id,
        channel=payload.channel,
    )


@register_router.post("/otp/confirm", response_model=RegisterOtpConfirmResponse)
async def confirm_otp(payload: RegisterOtpConfirmRequest):
    return await auth_service.confirm_registration_otp(
        challenge_id=payload.challenge_id,
        email_code=payload.email_code,
        phone_code=payload.phone_code,
    )


router.include_router(auth_router)
router.include_router(register_router)
