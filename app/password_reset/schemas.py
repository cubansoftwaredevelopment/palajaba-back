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
