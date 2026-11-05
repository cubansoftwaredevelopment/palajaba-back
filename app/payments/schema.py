from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.subscriptions.schemas import BillingPeriod, PlanTier


class QvaPayAccountRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    skip_verification: bool = False

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


class DisputeOpenRequest(BaseModel):
    text: str = Field(..., min_length=3, max_length=2000)
    images: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Explica el motivo de la disputa.")
        return cleaned

    @field_validator("images")
    @classmethod
    def normalize_images(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if str(item or "").strip()]


class RefundLineRequest(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., ge=0, le=99)


class StoreRefundRequest(BaseModel):
    items: list[RefundLineRequest] = Field(..., min_length=1)
    refund_delivery: bool = False
    text: str = Field(..., min_length=3, max_length=2000)
    images: list[str] = Field(..., min_length=1, max_length=6)

    @field_validator("text")
    @classmethod
    def normalize_refund_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Escribe el motivo del reembolso.")
        return cleaned

    @field_validator("images")
    @classmethod
    def normalize_refund_images(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if str(item or "").strip()]
        if not cleaned:
            raise ValueError("Adjunta al menos una imagen del motivo.")
        return cleaned


class CustomerOrderNotificationPublic(BaseModel):
    id: str
    title: str
    content: str
    kind: str
    images: list[str] = Field(default_factory=list)
    order_id: str
    created_at: datetime
    read_at: datetime | None = None


class CustomerDeviceRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)
    platform: str = Field(..., pattern="^(android|ios)$")


class CustomerDeviceDelete(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)


class DisputeRulingRequest(BaseModel):
    winner: Literal["buyer", "seller"]
    reason: str = Field(..., min_length=3, max_length=500)
    items: list[RefundLineRequest] | None = None
    refund_delivery: bool = False

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Escribe el motivo del fallo.")
        return cleaned
