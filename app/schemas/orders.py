from app.utils.datetime import UtcDateTime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

OrderStatus = Literal["pending_confirmation", "completed"]
InvoiceType = Literal["store", "transporter"]
OrderOrigin = Literal["platform", "manual"]
PAYMENT_CURRENCIES = ("CUP", "USD", "EUR", "MLC")


class OrderItemCreate(BaseModel):
    product_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(..., ge=1, le=99)
    unit_price: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=8)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El nombre del producto es obligatorio.")
        return stripped

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class OrderItemUpdate(BaseModel):
    product_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(..., ge=1, le=99)
    unit_price: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=8)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El nombre del producto es obligatorio.")
        return stripped

    @field_validator("currency")
    @classmethod
    def normalize_item_currency(cls, value: str) -> str:
        return value.strip().upper()


class DeliveryInfo(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=120)
    address: str = Field(..., min_length=1, max_length=500)
    phone_primary: str = Field(..., min_length=8, max_length=20)
    phone_secondary: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("recipient_name", "address")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Este campo es obligatorio.")
        return stripped

    @field_validator("notes")
    @classmethod
    def strip_optional_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class BuyerZone(BaseModel):
    province_id: str
    province_name: str
    municipality_id: str
    municipality_name: str


class CreateOrderRequest(BaseModel):
    store_id: str = Field(..., min_length=1)
    items: list[OrderItemCreate] = Field(..., min_length=1)
    delivery: DeliveryInfo | None = None
    buyer_zone: BuyerZone | None = None
    payment_currency: str | None = Field(default=None, min_length=3, max_length=8)

    @field_validator("payment_currency")
    @classmethod
    def normalize_payment_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in PAYMENT_CURRENCIES:
            raise ValueError("Moneda de pago no válida.")
        return normalized


class CreateSellerManualOrderRequest(BaseModel):
    items: list[OrderItemCreate] = Field(..., min_length=1)
    delivery: DeliveryInfo | None = None
    buyer_zone: BuyerZone | None = None
    payment_currency: str | None = Field(default=None, min_length=3, max_length=8)

    @field_validator("payment_currency")
    @classmethod
    def normalize_payment_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in PAYMENT_CURRENCIES:
            raise ValueError("Moneda de pago no válida.")
        return normalized


class OrderItemPublic(BaseModel):
    product_id: str
    name: str
    quantity: int
    unit_price: float
    currency: str
    line_total: float


class OrderSubtotalPublic(BaseModel):
    currency: str
    amount: float


class OrderPublic(BaseModel):
    id: str
    store_id: str
    store_name: str
    status: OrderStatus
    items: list[OrderItemPublic]
    subtotals: list[OrderSubtotalPublic]
    delivery_requested: bool
    delivery: DeliveryInfo | None = None
    delivery_price: float | None = None
    delivery_currency: str | None = None
    payment_currency: str | None = None
    buyer_zone: BuyerZone | None = None
    origin: OrderOrigin = "platform"
    created_at: UtcDateTime
    updated_at: UtcDateTime
    completed_at: UtcDateTime | None = None


class UpdateOrderRequest(BaseModel):
    status: OrderStatus | None = None
    items: list[OrderItemUpdate] | None = None
    delivery_price: float | None = Field(default=None, ge=0)
    delivery_currency: str | None = Field(default=None, min_length=3, max_length=8)
    payment_currency: str | None = Field(default=None, min_length=3, max_length=8)

    @field_validator("payment_currency", "delivery_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in PAYMENT_CURRENCIES:
            raise ValueError("Moneda no válida.")
        return normalized
