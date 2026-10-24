from fastapi import APIRouter, Depends, Query

from app.auth.utils import require_admin
from app.auth.schemas import RegistrationPublic
from app.subscriptions.schemas import (
    BillingPeriod,
    PlanTier,
    RegistrationSubscriptionReplace,
)
from app.auth import registrations as registration_service
from app.utils.dates import parse_subscription_end

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.patch(
    "/registrations/{registration_id}/subscription",
    response_model=RegistrationPublic,
)
async def update_subscription(
    registration_id: str,
    payload: RegistrationSubscriptionReplace,
    _: dict = Depends(require_admin),
):
    return await registration_service.replace_subscription(registration_id, payload)


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
    keep_gestor_ids: list[str] = Query(default=[]),
    _: dict = Depends(require_admin),
):
    parsed_end = parse_subscription_end(subscription_ends_at) if subscription_ends_at else None
    return await registration_service.renew_registration(
        registration_id,
        parsed_end,
        payment_amount_cup,
        plan_tier=plan_tier,
        billing_period=billing_period,
        keep_gestor_ids=keep_gestor_ids,
    )
