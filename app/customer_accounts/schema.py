from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if digits.startswith("53") and len(digits) == 10:
        digits = digits[2:]
    if len(digits) != 8:
        raise ValueError("El teléfono debe tener 8 dígitos.")
    return digits


class CustomerRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=254)
    phone: str
    identity_card: str
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("Ingresa un correo válido.")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone_field(cls, value: str) -> str:
        return _normalize_phone(value)

    @field_validator("identity_card")
    @classmethod
    def validate_identity_card(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El carnet de identidad es obligatorio.")
        return value


class CustomerOtpStartResponse(BaseModel):
    challenge_id: str
    email_expires_at: str | None = None
    phone_expires_at: str | None = None
    message: str
    otp_bypassed: bool = False


class CustomerOtpResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    channel: str = Field(..., pattern="^(email|phone)$")


class CustomerOtpConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    email_code: str = Field(..., min_length=4, max_length=8)
    phone_code: str = Field(..., min_length=4, max_length=8)


class CustomerLoginRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("phone")
    @classmethod
    def normalize_login_phone(cls, value: str) -> str:
        return _normalize_phone(value)


class CustomerPublic(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str
    identity_card: str
    profile_photo_url: str | None = None
    addresses: list[dict[str, Any]] = Field(default_factory=list)
    favorite_product_ids: list[str] = Field(default_factory=list)
    favorites: list[dict[str, Any]] = Field(default_factory=list)


class CustomerLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer: CustomerPublic


class CustomerAddressRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=48)
    address: str = Field(..., min_length=3, max_length=300)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    @model_validator(mode="after")
    def validate_pin_pair(self):
        return self


class CustomerEmailUpdateRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("Ingresa un correo válido.")
        return normalized


class CustomerPhoneUpdateRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def normalize_phone_field(cls, value: str) -> str:
        return _normalize_phone(value)


class CustomerContactOtpStartResponse(BaseModel):
    challenge_id: str
    expires_at: str | None = None
    message: str
    otp_bypassed: bool = False


class CustomerContactOtpConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    code: str = Field(..., min_length=4, max_length=8)


class CustomerIdentityCardUpdateRequest(BaseModel):
    identity_card: str = Field(..., min_length=1, max_length=64)

    @field_validator("identity_card")
    @classmethod
    def normalize_identity_card(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El carnet de identidad es obligatorio.")
        return value


class CustomerPasswordResetStartRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def normalize_phone_field(cls, value: str) -> str:
        return _normalize_phone(value)


class CustomerPasswordResetStartResponse(BaseModel):
    challenge_id: str
    phone_hint: str
    expires_at: str | None = None
    message: str
    otp_bypassed: bool = False


class CustomerPasswordResetResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)


class CustomerPasswordResetConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    code: str = Field(..., min_length=4, max_length=8)


class CustomerPasswordResetCompleteRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=6, max_length=128)


class CustomerPasswordResetConfirmResponse(BaseModel):
    challenge_id: str
    message: str


class CustomerPasswordResetCompleteResponse(BaseModel):
    message: str


