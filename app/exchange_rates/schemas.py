from datetime import datetime

from pydantic import BaseModel, Field


class ExchangeRatesPublic(BaseModel):
    cup_per_unit: dict[str, float] = Field(
        description="Cuántos CUP equivalen a 1 unidad de cada moneda.",
    )
    currencies: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    source: str = "elTOQUE"
    attribution: str = "Tasas de elTOQUE (TRMI)"
    reference_date: str | None = None
    reference_time: str | None = None
    stale: bool = False
    rates_available: bool = Field(
        default=False,
        description="False si no hay tasas reales de elTOQUE ni caché persistido.",
    )
