from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies import require_admin
from app.schemas.admin import AdminLoginRequest, AdminLoginResponse
from app.schemas.notifications import (
    AdminNotificationBroadcastPublic,
    AdminNotificationCreate,
    AdminNotificationSendResult,
)
from app.schemas.admin_stats import AdminStatsSummary
from app.schemas.registration import RegistrationPublic
from app.utils.dates import parse_subscription_end
from app.security import create_admin_token
from app.services import admins as admin_service
from app.services import admin_stats as admin_stats_service
from app.services import notifications as notification_service
from app.services import registrations as registration_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest):
    from fastapi import HTTPException, status

    admin = await admin_service.authenticate_admin(
        payload.username.strip(),
        payload.password,
    )
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )

    return AdminLoginResponse(
        access_token=create_admin_token(
            username=admin["username"],
            admin_id=str(admin["_id"]),
        )
    )


@router.get("/registrations", response_model=list[RegistrationPublic])
async def list_registrations(
    status: Literal["pending", "approved", "rejected", "all"] = Query(
        default="pending"
    ),
    _: dict = Depends(require_admin),
):
    return await registration_service.list_registrations(status)


@router.get("/registrations/{registration_id}", response_model=RegistrationPublic)
async def get_registration(
    registration_id: str,
    _: dict = Depends(require_admin),
):
    return await registration_service.get_registration(registration_id)


@router.post(
    "/registrations/{registration_id}/approve",
    response_model=RegistrationPublic,
)
async def approve_registration(
    registration_id: str,
    payment_amount_cup: int = Query(
        ...,
        gt=0,
        description="Monto real transferido en CUP",
    ),
    subscription_ends_at: str | None = Query(
        default=None,
        description="Fecha de fin de suscripción (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    _: dict = Depends(require_admin),
):
    return await registration_service.approve_registration(
        registration_id,
        parse_subscription_end(subscription_ends_at),
        payment_amount_cup,
    )


@router.get("/stats/summary", response_model=AdminStatsSummary)
async def stats_summary(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    _: dict = Depends(require_admin),
):
    now = datetime.now(UTC)
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return await admin_stats_service.get_stats_summary(target_year, target_month)


@router.post(
    "/registrations/{registration_id}/reject",
    response_model=RegistrationPublic,
)
async def reject_registration(
    registration_id: str,
    _: dict = Depends(require_admin),
):
    return await registration_service.reject_registration(registration_id)


@router.patch(
    "/registrations/{registration_id}/subscription",
    response_model=RegistrationPublic,
)
async def update_subscription(
    registration_id: str,
    subscription_ends_at: str = Query(
        ...,
        description="Nueva fecha de fin (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    _: dict = Depends(require_admin),
):
    parsed = parse_subscription_end(subscription_ends_at)
    if parsed is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fecha de suscripción inválida.",
        )
    return await registration_service.update_subscription_end(
        registration_id,
        parsed,
    )


@router.patch(
    "/registrations/{registration_id}/payment",
    response_model=RegistrationPublic,
)
async def update_payment(
    registration_id: str,
    payment_amount_cup: int = Query(
        ...,
        gt=0,
        description="Monto transferido en CUP",
    ),
    _: dict = Depends(require_admin),
):
    return await registration_service.update_payment_amount(
        registration_id,
        payment_amount_cup,
    )


@router.get("/notifications", response_model=list[AdminNotificationBroadcastPublic])
async def list_notifications(_: dict = Depends(require_admin)):
    return await notification_service.list_admin_broadcasts()


@router.post("/notifications", response_model=AdminNotificationSendResult)
async def send_notification(
    payload: AdminNotificationCreate,
    admin_payload: dict = Depends(require_admin),
):
    return await notification_service.send_notification_to_sellers(
        admin_payload["admin_id"],
        payload.title,
        payload.content,
    )
