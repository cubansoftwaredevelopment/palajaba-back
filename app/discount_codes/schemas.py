from pydantic import BaseModel, Field, field_validator

from app.utils.datetime import UtcDateTime


class DiscountCodePublic(BaseModel):
    id: str
    code: str
    percent_off: int
    is_active: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime


class DiscountCodeCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    percent_off: int = Field(..., ge=1, le=100)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def strip_code(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El código no puede estar vacío.")
        return stripped


class DiscountCodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=32)
    percent_off: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def strip_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("El código no puede estar vacío.")
        return stripped


class DiscountCodesAvailabilityPublic(BaseModel):
    available: bool


class ValidateDiscountCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    plan_tier: str = "standard"
    billing_period: str = "monthly"

    @field_validator("code")
    @classmethod
    def strip_code(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Ingresa un código de descuento.")
        return stripped


class ValidateDiscountCodePublic(BaseModel):
    code: str
    percent_off: int
    original_amount_cup: int
    discounted_amount_cup: int


class DiscountCodeDeleteResult(BaseModel):
    id: str
    message: str
