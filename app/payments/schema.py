from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.subscriptions.schemas import BillingPeriod, PlanTier


class QvaPayAccountRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lstrip("@").lower()


class QvaPayAccountPublic(BaseModel):
    username: str | None = None
    verified: bool = False


class SubscriptionPlanCheckoutRequest(BaseModel):
    plan_tier: PlanTier
    billing_period: BillingPeriod


class SubscriptionPlanCheckoutPublic(BaseModel):
    purchase_id: str
    plan_tier: PlanTier
    billing_period: BillingPeriod
    plan_amount_usd: float
    invoice_amount_usd: float
    payment_url: str
    status: str


class SubscriptionPlanCheckoutStatus(BaseModel):
    purchase_id: str
    plan_tier: PlanTier
    billing_period: BillingPeriod
    invoice_amount_usd: float
    payment_url: str
    status: str


class SellerAcceptPaymentRequest(BaseModel):
    delivery_price: float | None = Field(default=None, ge=0)
    delivery_currency: str | None = Field(default=None, min_length=3, max_length=8)

    @field_validator("delivery_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class EvidenceSubmitRequest(BaseModel):
    content: dict[str, Any]


class CustomerOrderNotificationPublic(BaseModel):
    id: str
    title: str
    content: str
    kind: str
    order_id: str
    created_at: datetime
    read_at: datetime | None = None


class CustomerDeviceRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)
    platform: str = Field(..., pattern="^(android|ios)$")


class CustomerDeviceDelete(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)
