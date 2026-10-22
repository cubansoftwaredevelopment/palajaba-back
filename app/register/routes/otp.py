from fastapi import APIRouter, HTTPException, status

from app.register.challenges import (
    confirm_registration_otp,
    resend_registration_otp,
    start_registration_otp,
)
from app.register.schemas.otp import (
    RegisterOtpConfirmRequest,
    RegisterOtpConfirmResponse,
    RegisterOtpResendRequest,
    RegisterOtpStartResponse,
    RegisterRequest,
    RegisterResponse,
)

router = APIRouter()


@router.post("", response_model=RegisterResponse, status_code=201)
async def register_seller(_payload: RegisterRequest):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Verifica tu correo y teléfono para crear la tienda.",
    )


@router.post("/otp/start", response_model=RegisterOtpStartResponse)
async def start_otp(payload: RegisterRequest):
    return await start_registration_otp(payload)


@router.post("/otp/resend", response_model=RegisterOtpStartResponse)
async def resend_otp(payload: RegisterOtpResendRequest):
    return await resend_registration_otp(
        challenge_id=payload.challenge_id,
        channel=payload.channel,
    )


@router.post("/otp/confirm", response_model=RegisterOtpConfirmResponse)
async def confirm_otp(payload: RegisterOtpConfirmRequest):
    return await confirm_registration_otp(
        challenge_id=payload.challenge_id,
        email_code=payload.email_code,
        phone_code=payload.phone_code,
    )
