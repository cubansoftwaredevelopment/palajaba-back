from pydantic import BaseModel, Field, field_validator


class PlatformSettingsPublic(BaseModel):
    renewal_contact_phone: str | None = None


class PlatformSettingsUpdate(BaseModel):
    renewal_contact_phone: str = Field(..., min_length=8, max_length=20)

    @field_validator("renewal_contact_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) != 8:
            raise ValueError("El teléfono debe tener 8 dígitos (Cuba).")
        return digits


class PlatformRenewalContactPublic(BaseModel):
    renewal_contact_phone: str | None = None
