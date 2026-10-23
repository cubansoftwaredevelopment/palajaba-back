from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.registration import PlanTier, RegistrationStatus

BillingPeriod = Literal["monthly", "quarterly", "yearly"]
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
