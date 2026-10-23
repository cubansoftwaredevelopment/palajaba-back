from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.constants import CURRENCY_CODES, DEFAULT_PLAN_PRICES

PlanCurrency = Literal["CUP", "USD", "EUR", "MLC"]
PlanTierKey = Literal["standard", "pro", "premium"]
BillingPeriodKey = Literal["monthly", "quarterly", "yearly"]


class PlanPriceConfig(BaseModel):
    amount: float = Field(..., ge=0)
    currency: PlanCurrency = "USD"

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        code = str(value or "").strip().upper()
        if code not in CURRENCY_CODES:
            raise ValueError("Moneda no soportada.")
        return code


class PlanPeriodPrices(BaseModel):
    monthly: PlanPriceConfig
    quarterly: PlanPriceConfig
    yearly: PlanPriceConfig


class PlanPricesSettings(BaseModel):
    standard: PlanPeriodPrices
    pro: PlanPeriodPrices
    premium: PlanPeriodPrices

    def get_price(self, tier: str, period: str) -> PlanPriceConfig:
        if tier == "premium":
            tier_prices = self.premium
        elif tier == "pro":
            tier_prices = self.pro
        else:
            tier_prices = self.standard
        if period == "yearly":
            return tier_prices.yearly
        if period == "quarterly":
            return tier_prices.quarterly
        return tier_prices.monthly


def default_plan_prices() -> PlanPricesSettings:
    return PlanPricesSettings.model_validate(DEFAULT_PLAN_PRICES)


class PlatformSettingsPublic(BaseModel):
    renewal_contact_phone: str | None = None
    plan_prices: PlanPricesSettings = Field(default_factory=default_plan_prices)


class PlatformSettingsUpdate(BaseModel):
    renewal_contact_phone: str = Field(..., min_length=8, max_length=20)
    plan_prices: PlanPricesSettings

    @field_validator("renewal_contact_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos (Cuba).")
        return digits


class PlatformRenewalContactPublic(BaseModel):
    renewal_contact_phone: str | None = None


class PlatformPlanPricesPublic(BaseModel):
    plan_prices: PlanPricesSettings
