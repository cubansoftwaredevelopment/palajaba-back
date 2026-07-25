from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies import require_admin
from app.schemas.discount_code import (
    DiscountCodeCreate,
    DiscountCodeDeleteResult,
    DiscountCodePublic,
    DiscountCodeUpdate,
)
from app.schemas.admin import AdminLoginRequest, AdminLoginResponse
from app.schemas.notifications import (
    AdminNotificationBroadcastPublic,
    AdminNotificationCreate,
    AdminNotificationSendResult,
)
from app.schemas.admin_stats import (
    AdminBusinessesByProvince,
    AdminRevenueChart,
    AdminStatsSummary,
)
from app.schemas.platform_settings import PlatformSettingsPublic, PlatformSettingsUpdate
from app.schemas.registration import BillingPeriod, PlanTier, RegistrationDeleteResult, RegistrationPublic
from app.schemas.seller_feedback import (
    AdminFeedbackDeleteResult,
    AdminFeedbackPublic,
    AdminFeedbackUnreadCount,
)
from app.utils.dates import parse_subscription_end
from app.security import create_admin_token
from app.services import admins as admin_service
from app.services import admin_stats as admin_stats_service
from app.services import discount_codes as discount_codes_service
from app.services import notifications as notification_service
from app.services import platform_settings as platform_settings_service
from app.services import registrations as registration_service
from app.services import seller_feedback as seller_feedback_service
from app.services import seller_deletion as seller_deletion_service
from app.services.seller_stats import Granularity

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
    status: Literal["pending", "approved", "rejected", "expired", "all"] = Query(
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


@router.delete(
    "/registrations/{registration_id}",
    response_model=RegistrationDeleteResult,
)
async def delete_registration(
    registration_id: str,
    _: dict = Depends(require_admin),
):
    result = await seller_deletion_service.delete_registration_document(registration_id)
    return RegistrationDeleteResult(**result)


@router.post(
    "/registrations/{registration_id}/approve",
    response_model=RegistrationPublic,
)
async def approve_registration(
    registration_id: str,
    payment_amount_cup: int = Query(
        ...,
        ge=0,
        description="Monto real transferido en CUP (0 = acceso gratuito)",
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


@router.get("/stats/businesses-by-province", response_model=AdminBusinessesByProvince)
async def businesses_by_province(_: dict = Depends(require_admin)):
    return await admin_stats_service.get_businesses_by_province()


@router.get("/stats/revenue", response_model=AdminRevenueChart)
async def stats_revenue(
    granularity: Granularity,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    _: dict = Depends(require_admin),
):
    now = datetime.now(UTC)
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return await admin_stats_service.get_revenue_chart(
        granularity=granularity,
        year=None if granularity == "monthly" else target_year,
        month=None if granularity == "monthly" else target_month,
    )


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
    plan_tier: PlanTier | None = Query(default=None),
    billing_period: BillingPeriod | None = Query(default=None),
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
        plan_tier=plan_tier,
        billing_period=billing_period,
    )


@router.post(
    "/registrations/{registration_id}/renew",
    response_model=RegistrationPublic,
)
async def renew_registration(
    registration_id: str,
    payment_amount_cup: int = Query(
        ...,
        ge=0,
        description="Monto transferido en CUP (0 = acceso gratuito)",
    ),
    subscription_ends_at: str | None = Query(
        default=None,
        description="Fecha de fin de suscripción (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    plan_tier: PlanTier | None = Query(default=None),
    billing_period: BillingPeriod | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    parsed_end = parse_subscription_end(subscription_ends_at) if subscription_ends_at else None
    return await registration_service.renew_registration(
        registration_id,
        parsed_end,
        payment_amount_cup,
        plan_tier=plan_tier,
        billing_period=billing_period,
    )


@router.patch(
    "/registrations/{registration_id}/payment",
    response_model=RegistrationPublic,
)
async def update_payment(
    registration_id: str,
    payment_amount_cup: int = Query(
        ...,
        ge=0,
        description="Monto transferido en CUP (0 = acceso gratuito)",
    ),
    _: dict = Depends(require_admin),
):
    return await registration_service.update_payment_amount(
        registration_id,
        payment_amount_cup,
    )


@router.get("/discount-codes", response_model=list[DiscountCodePublic])
async def list_discount_codes(_: dict = Depends(require_admin)):
    return await discount_codes_service.list_discount_codes()


@router.post("/discount-codes", response_model=DiscountCodePublic, status_code=201)
async def create_discount_code(
    payload: DiscountCodeCreate,
    _: dict = Depends(require_admin),
):
    return await discount_codes_service.create_discount_code(
        code=payload.code,
        percent_off=payload.percent_off,
        is_active=payload.is_active,
    )


@router.patch("/discount-codes/{discount_code_id}", response_model=DiscountCodePublic)
async def update_discount_code(
    discount_code_id: str,
    payload: DiscountCodeUpdate,
    _: dict = Depends(require_admin),
):
    return await discount_codes_service.update_discount_code(discount_code_id, payload)


@router.delete("/discount-codes/{discount_code_id}", response_model=DiscountCodeDeleteResult)
async def delete_discount_code(
    discount_code_id: str,
    _: dict = Depends(require_admin),
):
    return await discount_codes_service.delete_discount_code(discount_code_id)


@router.get("/feedback", response_model=list[AdminFeedbackPublic])
async def list_feedback(
    filter: Literal["all", "unread", "complaint", "suggestion"] = Query(default="all"),
    _: dict = Depends(require_admin),
):
    return await seller_feedback_service.list_admin_feedback(feedback_filter=filter)


@router.get("/feedback/unread-count", response_model=AdminFeedbackUnreadCount)
async def feedback_unread_count(_: dict = Depends(require_admin)):
    return await seller_feedback_service.get_admin_feedback_unread_count()


@router.patch("/feedback/{feedback_id}/read", response_model=AdminFeedbackPublic)
async def mark_feedback_read(
    feedback_id: str,
    _: dict = Depends(require_admin),
):
    return await seller_feedback_service.mark_admin_feedback_read(feedback_id)


@router.delete("/feedback/{feedback_id}", response_model=AdminFeedbackDeleteResult)
async def delete_feedback(
    feedback_id: str,
    _: dict = Depends(require_admin),
):
    return await seller_feedback_service.delete_admin_feedback(feedback_id)


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
        payload.audience,
    )


@router.get("/settings", response_model=PlatformSettingsPublic)
async def get_settings(_: dict = Depends(require_admin)):
    return await platform_settings_service.get_platform_settings()


@router.patch("/settings", response_model=PlatformSettingsPublic)
async def update_settings(
    payload: PlatformSettingsUpdate,
    _: dict = Depends(require_admin),
):
    return await platform_settings_service.update_platform_settings(payload)
