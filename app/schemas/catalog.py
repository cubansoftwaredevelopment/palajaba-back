from pydantic import BaseModel, Field, field_validator


class CatalogCategoryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)


class CatalogCategoryReorder(BaseModel):
    category_ids: list[str] = Field(..., min_length=1)

    @field_validator("category_ids")
    @classmethod
    def normalize_category_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            category_id = item.strip()
            if not category_id or category_id in seen:
                continue
            seen.add(category_id)
            normalized.append(category_id)
        if not normalized:
            raise ValueError("Debes enviar al menos una categoría.")
        return normalized


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
