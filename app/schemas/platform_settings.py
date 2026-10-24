from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import CURRENCY_CODES, DEFAULT_ADVERTISING_PRICES, DEFAULT_PLAN_PRICES
from app.utils.phone import normalize_admin_phone, normalize_phone_digits

PlanCurrency = Literal["CUP", "USD", "EUR", "MLC"]
PlanTierKey = Literal["standard", "pro", "premium"]
BillingPeriodKey = Literal["monthly", "quarterly", "yearly"]
AdvertisingPlanId = Literal["ads-10", "ads-20", "ads-30"]


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


class AdvertisingPlanPrice(BaseModel):
    amount: float = Field(..., ge=0)


class AdvertisingPricesSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    ads_10: AdvertisingPlanPrice = Field(alias="ads-10")
    ads_20: AdvertisingPlanPrice = Field(alias="ads-20")
    ads_30: AdvertisingPlanPrice = Field(alias="ads-30")

    def get_amount(self, plan_id: str) -> float:
        if plan_id == "ads-20":
            return float(self.ads_20.amount)
        if plan_id == "ads-30":
            return float(self.ads_30.amount)
        return float(self.ads_10.amount)


def default_advertising_prices() -> AdvertisingPricesSettings:
    return AdvertisingPricesSettings.model_validate(
        {
            plan_id: {"amount": amount}
            for plan_id, amount in DEFAULT_ADVERTISING_PRICES.items()
        }
    )


def normalize_admin_email(value: str | None) -> str | None:
    if value is None:
        return None
    email = str(value).strip().lower()
    if not email:
        return None
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Indica un correo válido.")
    return email


class PlatformAdminContact(BaseModel):
    email: str
    phone: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = normalize_admin_email(value)
        if not email:
            raise ValueError("Indica un correo válido.")
        return email

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        phone = normalize_admin_phone(value)
        if not phone:
            raise ValueError("Indica un teléfono válido.")
        return phone


class PlatformSettingsPublic(BaseModel):
    renewal_contact_phone: str | None = None
    plan_prices: PlanPricesSettings = Field(default_factory=default_plan_prices)
    advertising_prices: AdvertisingPricesSettings = Field(
        default_factory=default_advertising_prices
    )
    admins: list[PlatformAdminContact] = Field(default_factory=list)
    admin_email: str | None = None
    admin_phone: str | None = None


class PlatformSettingsUpdate(BaseModel):
    renewal_contact_phone: str | None = None
    plan_prices: PlanPricesSettings | None = None
    advertising_prices: AdvertisingPricesSettings | None = None
    admins: list[PlatformAdminContact] | None = None
    admin_email: str | None = None
    admin_phone: str | None = None

    @field_validator("renewal_contact_phone")
    @classmethod
    def validate_renewal_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        return normalize_phone_digits(raw)

    @field_validator("admin_email")
    @classmethod
    def validate_admin_email(cls, value: str | None) -> str | None:
        return normalize_admin_email(value)

    @field_validator("admin_phone")
    @classmethod
    def validate_admin_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_admin_phone(value)


class PlatformRenewalContactPublic(BaseModel):
    renewal_contact_phone: str | None = None


class PlatformPlanPricesPublic(BaseModel):
    plan_prices: PlanPricesSettings


class AdvertisingPlanPublic(BaseModel):
    id: str
    name: str
    eyebrow: str
    features: list[str]
    recommended: bool
    amount_usd: float
    exchange_fee_usd: float
    invoice_amount_usd: float


class AdvertisingPlansPublic(BaseModel):
    plans: list[AdvertisingPlanPublic]
