from fastapi import APIRouter

from app.schemas.discount_code import (
    DiscountCodesAvailabilityPublic,
    ValidateDiscountCodePublic,
    ValidateDiscountCodeRequest,
)
from app.schemas.exchange_rates import ExchangeRatesPublic
from app.schemas.platform_settings import PlatformRenewalContactPublic
from app.services import discount_codes as discount_codes_service
from app.services import exchange_rates as exchange_rates_service
from app.services import platform_settings as platform_settings_service

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/exchange-rates", response_model=ExchangeRatesPublic)
async def get_exchange_rates():
    return exchange_rates_service.build_exchange_rates_public()


@router.get("/renewal-contact", response_model=PlatformRenewalContactPublic)
async def get_renewal_contact():
    settings = await platform_settings_service.get_platform_settings()
    return PlatformRenewalContactPublic(
        renewal_contact_phone=settings.renewal_contact_phone,
    )


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
