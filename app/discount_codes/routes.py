from fastapi import APIRouter

from app.discount_codes.schemas import (
    DiscountCodesAvailabilityPublic,
    ValidateDiscountCodePublic,
    ValidateDiscountCodeRequest,
)
from app.discount_codes import service as discount_codes_service

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/discount-codes/availability", response_model=DiscountCodesAvailabilityPublic)
async def get_discount_codes_availability():
    available = await discount_codes_service.has_active_discount_codes()
    return DiscountCodesAvailabilityPublic(available=available)


@router.post("/discount-codes/validate", response_model=ValidateDiscountCodePublic)
async def validate_discount_code(payload: ValidateDiscountCodeRequest):
    return await discount_codes_service.validate_discount_code(
        payload.code,
        plan_tier=payload.plan_tier,
        billing_period=payload.billing_period,
    )
