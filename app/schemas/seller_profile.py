from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.phone import normalize_phone_digits


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


class StoreBannerPublic(BaseModel):
    id: str
    image_url: str
    sort_order: int = 0
    is_active: bool = True


class StoreBannerUpdate(BaseModel):
    is_active: bool


SOCIAL_PLATFORM_IDS = frozenset(
    {"instagram", "facebook", "tiktok", "youtube", "telegram", "x", "other"}
)


class SellerSocialLink(BaseModel):
    platform: str = Field(..., min_length=1, max_length=40)
    label: str | None = Field(default=None, max_length=40)
    value: str = Field(..., min_length=1, max_length=200)

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        platform = value.strip().lower()
        if platform not in SOCIAL_PLATFORM_IDS:
            raise ValueError("Elige una red social válida.")
        return platform

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Escribe el usuario o el enlace de la red social.")
        return stripped

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def normalize_link(self):
        if self.platform == "other":
            if not self.label:
                raise ValueError("Escribe el nombre de la red social.")
        else:
            self.label = None
        return self


class SellerProfileUpdate(BaseModel):
    business_location: BusinessLocation | None = None
    clear_business_location: bool = False
    business_area: BusinessArea
    delivery_areas: list[BusinessArea] = Field(default_factory=list, max_length=30)
    biography: str | None = Field(default=None, max_length=500)
    social_instagram: str | None = Field(default=None, max_length=80)
    social_facebook: str | None = Field(default=None, max_length=120)
    social_links: list[SellerSocialLink] = Field(default_factory=list, max_length=12)
    category_ids: list[str] = Field(..., min_length=1, max_length=5)
    offers_delivery: bool
    gestores_enabled: bool = False

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


class SellerPhoneUpdate(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return normalize_phone_digits(value)


class SellerEmailUpdate(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = str(value).strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("El correo no es válido.")
        return email


class SellerContactOtpStartResponse(BaseModel):
    challenge_id: str
    expires_at: str | None = None
    message: str


class SellerContactOtpResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)


class SellerContactOtpConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    code: str = Field(..., min_length=4, max_length=8)


class SellerStoreNameUpdate(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=120)

    @field_validator("store_name")
    @classmethod
    def strip_store_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Este campo es obligatorio.")
        return stripped
