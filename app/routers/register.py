from fastapi import APIRouter

from app.schemas.registration import RegisterRequest, RegisterResponse
from app.services import registrations as registration_service

router = APIRouter(prefix="/api/register", tags=["register"])


@router.post("", response_model=RegisterResponse, status_code=201)
async def register_seller(payload: RegisterRequest):
    registration = await registration_service.create_registration(
        transfer_id=payload.transfer_id,
        store_name=payload.store_name,
        phone=payload.phone,
        password=payload.password,
        billing_period=payload.billing_period,
    )
    return RegisterResponse(
        id=registration.id,
        status=registration.status,
        message=(
            "Solicitud recibida. Te notificaremos cuando verifiquemos tu pago."
        ),
    )
