from pydantic import BaseModel, Field, field_validator


class LaunchPromoStatusPublic(BaseModel):
    available: bool
    limit: int
    claimed_count: int
    slots_remaining: int


class LaunchPromoRegisterRequest(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=8, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("store_name")
    @classmethod
    def strip_store_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Este campo es obligatorio.")
        return stripped

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("53") and len(digits) == 10:
            digits = digits[2:]
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos.")
        return digits
