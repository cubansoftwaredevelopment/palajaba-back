from pydantic import BaseModel, Field

from app.schemas.seller_profile import BusinessArea, BusinessLocation, CategoryPublic


class MarketplaceStorePublic(BaseModel):
    id: str
    store_name: str
    store_slug: str
    phone: str
    profile_photo_url: str | None = None


class MarketplaceProductPublic(BaseModel):
    id: str
    global_category_id: str
    name: str
    description: str | None = None
    image_url: str
    base_price: float
    base_currency: str
    accepted_currencies: list[str] = Field(default_factory=list)
    offers_delivery: bool
    view_only: bool = False
    store: MarketplaceStorePublic
    category_name: str


class MarketplaceCategorySectionPublic(BaseModel):
    category_id: str
    category_name: str
    products: list[MarketplaceProductPublic] = Field(default_factory=list)
    total_products: int = 0
    has_more: bool = False


class MarketplaceHomeFeedPublic(BaseModel):
    province_id: str
    province_name: str
    municipality_id: str
    municipality_name: str
    sections: list[MarketplaceCategorySectionPublic] = Field(default_factory=list)
    total_products: int = 0


class MarketplaceCategoryProductsPublic(BaseModel):
    category_id: str
    category_name: str
    products: list[MarketplaceProductPublic] = Field(default_factory=list)
    total_products: int = 0
    limit: int
    offset: int
    has_more: bool = False


class MarketplaceStoreLocalSectionPublic(BaseModel):
    category_id: str
    category_name: str
    products: list[MarketplaceProductPublic] = Field(default_factory=list)
    total_products: int = 0
    has_more: bool = False


class MarketplaceStoreCatalogPublic(BaseModel):
    store: MarketplaceStorePublic
    biography: str | None = None
    social_instagram: str | None = None
    social_facebook: str | None = None
    business_location: BusinessLocation | None = None
    business_area: BusinessArea | None = None
    delivery_areas: list[BusinessArea] = Field(default_factory=list)
    categories: list[CategoryPublic] = Field(default_factory=list)
    offers_delivery: bool | None = None
    sections: list[MarketplaceStoreLocalSectionPublic] = Field(default_factory=list)
    total_products: int = 0


class MarketplaceStoreCategoryProductsPublic(BaseModel):
    category_id: str
    category_name: str
    products: list[MarketplaceProductPublic] = Field(default_factory=list)
    total_products: int = 0
    limit: int
    offset: int
    has_more: bool = False
