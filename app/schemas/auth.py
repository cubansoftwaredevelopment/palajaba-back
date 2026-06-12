from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.seller_profile import BusinessArea, BusinessLocation
from app.utils.datetime import UtcDateTime

LoginMethod = Literal["phone", "store_name"]


class SellerLoginRequest(BaseModel):
    method: LoginMethod
    password: str = Field(..., min_length=1, max_length=128)
    phone: str | None = None
    store_name: str | None = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("53") and len(digits) == 10:
            digits = digits[2:]
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos.")
        return digits

    @field_validator("store_name")
    @classmethod
    def normalize_store_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_method_fields(self):
        if self.method == "phone" and not self.phone:
            raise ValueError("El número de teléfono es obligatorio.")
        if self.method == "store_name" and not self.store_name:
            raise ValueError("El nombre de la tienda es obligatorio.")
        return self


class SellerPublic(BaseModel):
    id: str
    store_name: str
    phone: str
    billing_period: str
    plan_tier: str = "standard"
    has_statistics: bool = False
    has_recommendation_boost: bool = False
    subscription_ends_at: UtcDateTime | None = None
    profile_photo_url: str | None = None
    business_location: BusinessLocation | None = None
    business_area: BusinessArea | None = None
    delivery_areas: list[BusinessArea] = []
    biography: str | None = None
    social_instagram: str | None = None
    social_facebook: str | None = None
    category_ids: list[str] = []
    offers_delivery: bool | None = None
    profile_completed: bool = False
    profile_completed_at: UtcDateTime | None = None
    subscription_active: bool = True
    subscription_days_remaining: int | None = None
    subscription_hours_remaining: int | None = None


class SubscriptionExpiredPublic(BaseModel):
    code: Literal["subscription_expired"] = "subscription_expired"
    message: str
    store_name: str | None = None
    subscription_ends_at: UtcDateTime | None = None
    renewal_contact_phone: str | None = None


class SellerLoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    seller: SellerPublic | None = None
    subscription_expired: SubscriptionExpiredPublic | None = None
