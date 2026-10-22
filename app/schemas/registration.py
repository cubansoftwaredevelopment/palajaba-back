from typing import Literal

from pydantic import BaseModel, Field

from app.utils.datetime import UtcDateTime

BillingPeriod = Literal["monthly", "yearly"]
PlanTier = Literal["standard", "premium"]
RegistrationStatus = Literal["pending", "approved", "rejected", "expired"]


class RegistrationPublic(BaseModel):
    id: str
    transfer_id: str
    store_name: str
    email: str | None = None
    phone: str
    is_trial: bool = False
    billing_period: BillingPeriod
    plan_tier: PlanTier = "standard"
    status: RegistrationStatus
    subscription_starts_at: UtcDateTime | None = None
    subscription_ends_at: UtcDateTime | None = None
    expiry_notice_email_sent: bool = False
    expiry_notice_sms_sent: bool = False
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
    sales_total_cup: float = 0


class RegistrationDeleteResult(BaseModel):
    id: str
    store_name: str
    message: str
