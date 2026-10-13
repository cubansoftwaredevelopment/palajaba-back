from pydantic import BaseModel, Field


class AdminProductRow(BaseModel):
    id: str
    name: str
    category_name: str
    store_name: str
    price: float
    currency: str
    offers_delivery: bool
    subscription_active: bool
    locations: list[str] = Field(default_factory=list)


class AdminProductList(BaseModel):
    products: list[AdminProductRow] = Field(default_factory=list)
    total: int = 0
