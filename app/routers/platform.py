from fastapi import APIRouter

from app.schemas.exchange_rates import ExchangeRatesPublic
from app.schemas.platform_settings import PlatformRenewalContactPublic
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
