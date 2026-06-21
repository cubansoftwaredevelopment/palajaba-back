from pydantic import BaseModel, Field

from app.schemas.seller_profile import BusinessArea, BusinessLocation, CategoryPublic


class MarketplaceStorePublic(BaseModel):
    id: str
    store_name: str
    store_slug: str
    phone: str
    profile_photo_url: str | None = None


class MarketplaceBusinessPublic(BaseModel):
    store: MarketplaceStorePublic
    business_area: BusinessArea | None = None
    offers_delivery: bool | None = None
    categories: list[CategoryPublic] = Field(default_factory=list)
    popularity: int = 0
    is_local: bool = False
    published_product_count: int = 0
    pickup_required: bool = False
    pickup_municipality_name: str | None = None
    pickup_notice: str | None = None


class MarketplaceBusinessesPublic(BaseModel):
    province_id: str
    province_name: str
    municipality_id: str
    municipality_name: str
    query: str = ""
    category_id: str | None = None
    category_name: str | None = None
    businesses: list[MarketplaceBusinessPublic] = Field(default_factory=list)
    total_businesses: int = 0
    limit: int
    offset: int
    has_more: bool = False


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
    is_available: bool = True
    view_only: bool = False
    pickup_required: bool = False
    pickup_municipality_name: str | None = None
    pickup_notice: str | None = None
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


class MarketplaceSearchPublic(BaseModel):
    query: str = ""
    category_id: str | None = None
    category_name: str | None = None
    products: list[MarketplaceProductPublic] = Field(default_factory=list)
    total_products: int = 0
    limit: int
    offset: int
    has_more: bool = False


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


class JabaSyncItemRequest(BaseModel):
    product_id: str = Field(..., min_length=1)
    name: str = Field(default="Producto", min_length=1)


class JabaSyncRequest(BaseModel):
    items: list[JabaSyncItemRequest] = Field(default_factory=list, max_length=50)
    province_id: str | None = None
    municipality_id: str | None = None
    municipios_adicionales: list[str] | None = None


class JabaRemovedProductPublic(BaseModel):
    product_id: str
    name: str
    reason: str
    message: str


class JabaSyncPublic(BaseModel):
    valid: list[MarketplaceProductPublic] = Field(default_factory=list)
    removed: list[JabaRemovedProductPublic] = Field(default_factory=list)
