from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.datetime import UtcDateTime

BillingPeriod = Literal["monthly", "yearly"]
PlanTier = Literal["standard", "premium"]
RegistrationStatus = Literal["pending", "approved", "rejected", "expired"]


class RegisterRequest(BaseModel):
    transfer_id: str = Field(..., min_length=1, max_length=64)
    store_name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=8, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)
    billing_period: BillingPeriod
    plan_tier: PlanTier = "standard"
    discount_code: str | None = None

    @field_validator("transfer_id", "store_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Este campo es obligatorio.")
        return stripped

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("53") and len(digits) == 10:
            digits = digits[2:]
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos.")
        return digits

    @field_validator("discount_code")
    @classmethod
    def normalize_discount_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return stripped


class RegisterResponse(BaseModel):
    id: str
    status: RegistrationStatus
    message: str


class RegistrationPublic(BaseModel):
    id: str
    transfer_id: str
    store_name: str
    phone: str
    billing_period: BillingPeriod
    plan_tier: PlanTier = "standard"
    status: RegistrationStatus
    subscription_starts_at: UtcDateTime | None = None
    subscription_ends_at: UtcDateTime | None = None
    rejection_reason: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    approved_at: UtcDateTime | None = None
    payment_amount_cup: int | None = None
    discount_code: str | None = None
    discount_percent: int | None = None
    expected_payment_cup: int | None = None
    is_launch_promo: bool = False
    store_slug: str | None = None
    profile_completed: bool = False
    total_product_count: int = 0
    published_product_count: int = 0
    view_only_product_count: int = 0
    unavailable_product_count: int = 0
    marketplace_visibility_notes: list[str] = Field(default_factory=list)


class RegistrationDeleteResult(BaseModel):
    id: str
    store_name: str
    message: str

