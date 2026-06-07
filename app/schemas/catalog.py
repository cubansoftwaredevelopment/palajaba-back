from pydantic import BaseModel, Field


class CatalogCategoryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)


class CatalogProductPublic(BaseModel):
    id: str
    category_id: str
    global_category_id: str
    global_category_name: str | None = None
    name: str
    description: str | None = None
    image_url: str
    base_price: float
    base_currency: str
    accepted_currencies: list[str] = Field(default_factory=list)
    offers_delivery: bool
    view_only: bool = False
    is_available: bool = True


class CatalogCategoryPublic(BaseModel):
    id: str
    name: str
    product_count: int = 0
    products: list[CatalogProductPublic] = Field(default_factory=list)


class CatalogSummaryPublic(BaseModel):
    categories: list[CatalogCategoryPublic]
    total_products: int = 0


class CurrencyPublic(BaseModel):
    code: str
    label: str
    symbol: str
