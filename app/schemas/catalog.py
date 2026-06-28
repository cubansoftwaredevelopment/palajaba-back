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


class CatalogCategoryProductSortUpdate(BaseModel):
    product_sort_mode: str = Field(..., min_length=1, max_length=32)

    @field_validator("product_sort_mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        from app.services.catalog_product_sort import normalize_product_sort_mode

        return normalize_product_sort_mode(value.strip().lower())


class CatalogProductReorder(BaseModel):
    product_ids: list[str] = Field(..., min_length=1)

    @field_validator("product_ids")
    @classmethod
    def normalize_product_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            product_id = item.strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            normalized.append(product_id)
        if not normalized:
            raise ValueError("Debes enviar al menos un producto.")
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
    popularity: int = 0
    sort_order: int = 0


class CatalogCategoryPublic(BaseModel):
    id: str
    name: str
    product_count: int = 0
    product_sort_mode: str = "popularity"
    products: list[CatalogProductPublic] = Field(default_factory=list)


class CatalogSummaryPublic(BaseModel):
    categories: list[CatalogCategoryPublic]
    total_products: int = 0


class CatalogThemeUpdate(BaseModel):
    catalog_theme: str = Field(..., min_length=1, max_length=32)

    @field_validator("catalog_theme")
    @classmethod
    def validate_theme(cls, value: str) -> str:
        from app.services.catalog_theme import parse_catalog_theme

        return parse_catalog_theme(value)


class CatalogThemePublic(BaseModel):
    catalog_theme: str


class CurrencyPublic(BaseModel):
    code: str
    label: str
    symbol: str
