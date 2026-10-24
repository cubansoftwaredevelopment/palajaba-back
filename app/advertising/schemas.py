from pydantic import BaseModel, Field


class AdvertisingCheckoutRequest(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=32)


class AdvertisingCheckoutPublic(BaseModel):
    purchase_id: str
    plan_id: str
    plan_name: str
    plan_amount_usd: float
    exchange_fee_usd: float
    invoice_amount_usd: float
    payment_url: str
