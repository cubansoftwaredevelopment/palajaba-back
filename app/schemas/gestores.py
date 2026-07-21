from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.datetime import UtcDateTime
from app.utils.phone import normalize_phone_digits

GestorCatalogAccessMode = Literal["all", "selected"]


class GestorCatalogAccess(BaseModel):
    """Configuración global del negocio: a qué productos puede acceder su red de gestores."""

    mode: GestorCatalogAccessMode = "selected"
    product_ids: list[str] = Field(default_factory=list)

    @field_validator("product_ids")
    @classmethod
    def normalize_product_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            product_id = str(item).strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            normalized.append(product_id)
        return normalized

    @model_validator(mode="after")
    def clear_ids_when_all(self):
        if self.mode == "all":
            self.product_ids = []
        return self


class GestorSelectedProduct(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=64)
    margin_amount: float = Field(..., ge=0)

    @field_validator("product_id")
    @classmethod
    def strip_product_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El producto es obligatorio.")
        return stripped


class GestorPublic(BaseModel):
    id: str
    seller_id: str
    username: str
    phone: str | None = None
    has_password: bool
    selected_products: list[GestorSelectedProduct] = Field(default_factory=list)
    created_at: UtcDateTime
    updated_at: UtcDateTime


class GestorCreateRequest(BaseModel):
    """Creación inicial por el negocio: solo username."""

    username: str = Field(..., min_length=2, max_length=32)


class GestorCatalogAccessUpdate(BaseModel):
    mode: GestorCatalogAccessMode
    product_ids: list[str] = Field(default_factory=list)

    @field_validator("product_ids")
    @classmethod
    def normalize_product_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            product_id = str(item).strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            normalized.append(product_id)
        return normalized

    @model_validator(mode="after")
    def clear_ids_when_all(self):
        if self.mode == "all":
            self.product_ids = []
        return self


class GestorCheckoutPhones(BaseModel):
    """Teléfonos habilitados en el checkout del catálogo del negocio."""

    gestor_ids: list[str] = Field(default_factory=list)
    include_store_phone: bool = True

    @field_validator("gestor_ids")
    @classmethod
    def normalize_gestor_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            gestor_id = str(item).strip()
            if not gestor_id or gestor_id in seen:
                continue
            seen.add(gestor_id)
            normalized.append(gestor_id)
        return normalized

    @model_validator(mode="after")
    def require_at_least_one_phone(self):
        if not self.include_store_phone and not self.gestor_ids:
            raise ValueError(
                "Debes dejar al menos un teléfono disponible: el del negocio o uno de tus gestores."
            )
        return self


class GestorCheckoutPhonesUpdate(BaseModel):
    gestor_ids: list[str] = Field(default_factory=list)
    include_store_phone: bool = True

    @field_validator("gestor_ids")
    @classmethod
    def normalize_gestor_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            gestor_id = str(item).strip()
            if not gestor_id or gestor_id in seen:
                continue
            seen.add(gestor_id)
            normalized.append(gestor_id)
        return normalized

    @model_validator(mode="after")
    def require_at_least_one_phone(self):
        if not self.include_store_phone and not self.gestor_ids:
            raise ValueError(
                "Debes dejar al menos un teléfono disponible: el del negocio o uno de tus gestores."
            )
        return self


class GestorSelectedProductsUpdate(BaseModel):
    """Selección de productos y márgenes del gestor."""

    products: list[GestorSelectedProduct] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_product_ids(self):
        seen: set[str] = set()
        for item in self.products:
            if item.product_id in seen:
                raise ValueError("No puedes repetir el mismo producto.")
            seen.add(item.product_id)
        return self


class GestorSetupRequest(BaseModel):
    """Primer ingreso: contraseña + teléfono (con setup_token del login)."""

    setup_token: str = Field(..., min_length=10)
    password: str = Field(..., min_length=6, max_length=128)
    phone: str = Field(..., min_length=8, max_length=20)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return normalize_phone_digits(value)


class GestorLoginRequest(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=120)
    username: str = Field(..., min_length=2, max_length=32)
    password: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("store_name", "username")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Este campo es obligatorio.")
        return stripped


class GestorLoginRequiresSetup(BaseModel):
    requires_setup: Literal[True] = True
    setup_token: str
    username: str
    store_name: str


class GestorLoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    gestor: GestorPublic | None = None
    requires_setup: GestorLoginRequiresSetup | None = None


class GestorDeleteResult(BaseModel):
    id: str
    message: str


class GestorAllowedProductPublic(BaseModel):
    """Producto habilitado por el negocio para la red / selección del gestor."""

    product_id: str
    name: str
    image_url: str
    base_price: float
    base_currency: str
    is_available: bool = True
    margin_amount: float | None = None
    display_price: float | None = None
    selected: bool = False
