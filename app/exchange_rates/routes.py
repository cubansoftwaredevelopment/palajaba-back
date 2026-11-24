from fastapi import APIRouter

from app.exchange_rates.schemas import ExchangeRatesPublic
from app.exchange_rates import service as exchange_rates_service

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/exchange-rates", response_model=ExchangeRatesPublic)
async def get_exchange_rates():
    return exchange_rates_service.build_exchange_rates_public()
