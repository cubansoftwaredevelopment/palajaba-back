from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class BusinessLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    label: str | None = Field(default=None, max_length=200)


class BusinessArea(BaseModel):
    province_id: str = Field(..., min_length=1, max_length=64)
    province_name: str = Field(..., min_length=1, max_length=120)
    municipality_id: str = Field(..., min_length=1, max_length=64)
    municipality_name: str = Field(..., min_length=1, max_length=120)


class CategoryPublic(BaseModel):
    id: str
    name: str


class SellerProfileUpdate(BaseModel):
    business_location: BusinessLocation | None = None
    clear_business_location: bool = False
    business_area: BusinessArea
    delivery_areas: list[BusinessArea] = Field(default_factory=list, max_length=30)
    biography: str | None = Field(default=None, max_length=500)
    social_instagram: str | None = Field(default=None, max_length=80)
    social_facebook: str | None = Field(default=None, max_length=120)
    category_ids: list[str] = Field(..., min_length=1, max_length=5)
    offers_delivery: bool

    @model_validator(mode="after")
    def validate_delivery_areas(self):
        if not self.offers_delivery:
            self.delivery_areas = []
        return self

    @field_validator("biography", "social_instagram", "social_facebook")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("category_ids")
    @classmethod
    def normalize_category_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for item in value:
            cat_id = item.strip().lower()
            if not cat_id or cat_id in seen:
                continue
            seen.add(cat_id)
            normalized.append(cat_id)
        if not normalized:
            raise ValueError("Selecciona al menos una categoría.")
        return normalized
