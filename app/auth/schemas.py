from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.products.schemas import CatalogPalette
from app.schemas.seller_profile import BusinessArea, BusinessLocation, SellerSocialLink, StoreBannerPublic
from app.schemas.gestores import GestorCatalogAccess
from app.utils.datetime import UtcDateTime

LoginMethod = Literal["phone", "store_name"]
BillingPeriod = Literal["monthly", "quarterly", "yearly"]
PlanTier = Literal["standard", "pro", "premium"]
RegistrationStatus = Literal["pending", "approved", "rejected", "expired"]


class SellerLoginRequest(BaseModel):
    method: LoginMethod
    password: str = Field(..., min_length=1, max_length=128)
    phone: str | None = None
    store_name: str | None = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("53") and len(digits) == 10:
            digits = digits[2:]
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos.")
        return digits

    @field_validator("store_name")
    @classmethod
    def normalize_store_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_method_fields(self):
        if self.method == "phone" and not self.phone:
            raise ValueError("El número de teléfono es obligatorio.")
        if self.method == "store_name" and not self.store_name:
            raise ValueError("El nombre de la tienda es obligatorio.")
        return self


class SellerPublic(BaseModel):
    id: str
    store_name: str
    store_slug: str | None = None
    phone: str
    email: str | None = None
    is_trial: bool = False
    billing_period: str
    plan_tier: str = "standard"
    has_statistics: bool = False
    has_recommendation_boost: bool = False
    has_store_banners: bool = False
    has_full_store_customization: bool = False
    has_product_discounts: bool = False
    subscription_ends_at: UtcDateTime | None = None
    profile_photo_url: str | None = None
    business_location: BusinessLocation | None = None
    business_area: BusinessArea | None = None
    delivery_areas: list[BusinessArea] = []
    biography: str | None = None
    social_instagram: str | None = None
    social_facebook: str | None = None
    social_links: list[SellerSocialLink] = Field(default_factory=list)
    category_ids: list[str] = []
    offers_delivery: bool | None = None
    gestores_enabled: bool = False
    profile_completed: bool = False
    profile_completed_at: UtcDateTime | None = None
    subscription_active: bool = True
    subscription_days_remaining: int | None = None
    subscription_hours_remaining: int | None = None
    catalog_theme: str = "default"
    catalog_palette: CatalogPalette | None = None
    store_banners: list[StoreBannerPublic] = Field(default_factory=list)
    gestor_catalog_access: GestorCatalogAccess = Field(
        default_factory=lambda: GestorCatalogAccess(mode="selected", product_ids=[])
    )


class SubscriptionExpiredPublic(BaseModel):
    code: Literal["subscription_expired"] = "subscription_expired"
    message: str
    store_name: str | None = None
    subscription_ends_at: UtcDateTime | None = None
    renewal_contact_phone: str | None = None


class SellerLoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    seller: SellerPublic | None = None
    subscription_expired: SubscriptionExpiredPublic | None = None


from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

LoginMethod = Literal["phone", "store_name"]
OtpChannel = Literal["email", "phone"]


class PasswordResetStartRequest(BaseModel):
    method: LoginMethod
    phone: str | None = None
    store_name: str | None = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("53") and len(digits) == 10:
            digits = digits[2:]
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos.")
        return digits

    @field_validator("store_name")
    @classmethod
    def normalize_store_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_method_fields(self):
        if self.method == "phone" and not self.phone:
            raise ValueError("El número de teléfono es obligatorio.")
        if self.method == "store_name" and not self.store_name:
            raise ValueError("El nombre de la tienda es obligatorio.")
        return self


class PasswordResetStartResponse(BaseModel):
    challenge_id: str
    email_hint: str
    phone_hint: str
    email_expires_at: str | None = None
    phone_expires_at: str | None = None
    message: str


class PasswordResetResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    channel: OtpChannel


class PasswordResetConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    email_code: str = Field(..., min_length=4, max_length=8)
    phone_code: str = Field(..., min_length=4, max_length=8)


class PasswordResetConfirmResponse(BaseModel):
    challenge_id: str
    message: str


class PasswordResetCompleteRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres.")
        return value


class PasswordResetCompleteResponse(BaseModel):
    message: str


RegisterKind = Literal["trial", "paid"]
OtpChannel = Literal["email", "phone"]


class RegisterRequest(BaseModel):
    transfer_id: str | None = Field(default=None, max_length=64)
    store_name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=5, max_length=254)
    phone: str = Field(..., min_length=8, max_length=20)
    password: str = Field(..., min_length=1, max_length=128)
    billing_period: BillingPeriod = "monthly"
    plan_tier: PlanTier = "standard"
    discount_code: str | None = None
    kind: RegisterKind = "paid"

    @field_validator("transfer_id")
    @classmethod
    def strip_transfer_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("store_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Este campo es obligatorio.")
        return stripped

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres.")
        return value

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("53") and len(digits) == 10:
            digits = digits[2:]
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos.")
        return digits

    @field_validator("discount_code")
    @classmethod
    def normalize_discount_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return stripped

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = str(value).strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("El correo no es válido.")
        return email

    @model_validator(mode="after")
    def require_transfer_for_paid(self) -> "RegisterRequest":
        if self.kind == "paid" and not (self.transfer_id or "").strip():
            raise ValueError("El ID de la transferencia es obligatorio.")
        if self.kind == "trial":
            self.transfer_id = None
            self.plan_tier = "standard"
            self.billing_period = "monthly"
            self.discount_code = None
        return self


class RegisterOtpStartResponse(BaseModel):
    challenge_id: str
    email_expires_at: str | None = None
    phone_expires_at: str | None = None
    message: str


class RegisterOtpResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    channel: OtpChannel


class RegisterOtpConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    email_code: str = Field(..., min_length=4, max_length=8)
    phone_code: str = Field(..., min_length=4, max_length=8)


class RegisterOtpConfirmResponse(BaseModel):
    id: str
    status: RegistrationStatus
    kind: RegisterKind
    message: str
    access_token: str | None = None


class RegisterResponse(BaseModel):
    id: str
    status: RegistrationStatus
    message: str


class RegistrationPublic(BaseModel):
    id: str
    transfer_id: str
    store_name: str
    email: str | None = None
    phone: str
    is_trial: bool = False
    billing_period: BillingPeriod
    plan_tier: PlanTier = "standard"
    status: RegistrationStatus
    subscription_starts_at: UtcDateTime | None = None
    subscription_ends_at: UtcDateTime | None = None
    expiry_notice_sms_sent: bool = False
    rejection_reason: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    approved_at: UtcDateTime | None = None
    payment_amount_cup: int | None = None
    discount_code: str | None = None
    discount_percent: int | None = None
    expected_payment_cup: int | None = None
    is_launch_promo: bool = False
    store_slug: str | None = None
    profile_completed: bool = False
    total_product_count: int = 0
    published_product_count: int = 0
    view_only_product_count: int = 0
    unavailable_product_count: int = 0
    marketplace_visibility_notes: list[str] = Field(default_factory=list)
    sales_total_cup: float = 0


class RegistrationDeleteResult(BaseModel):
    id: str
    store_name: str
    message: str
