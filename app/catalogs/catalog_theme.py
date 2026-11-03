from __future__ import annotations

import logging
import re
from typing import Any, Literal, TypedDict

from fastapi import HTTPException, status

from app.database import get_product_categories_collection, get_registrations_collection
from app.schemas.seller_profile import CategoryPublic
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)

CatalogTheme = Literal[
    "default",
    "grey",
    "red",
    "pink",
    "green",
    "blue",
    "purple",
    "orange",
    "yellow",
    "carmelita",
]
DEFAULT_CATALOG_THEME: CatalogTheme = "default"

CATALOG_THEMES: tuple[CatalogTheme, ...] = (
    "default",
    "grey",
    "red",
    "pink",
    "green",
    "blue",
    "purple",
    "orange",
    "yellow",
    "carmelita",
)

PALETTE_SLOTS: tuple[str, ...] = ("primary", "background", "accent", "secondary")

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

# Tokens semánticos alineados con index.css (.catalog-theme-scope.*)
THEME_TOKENS: dict[str, dict[str, str]] = {
    "default": {
        "primary": "#59802c",
        "background": "#fdfbf2",
        "accent": "#f5c71a",
        "secondary": "#7b4c38",
    },
    "grey": {
        "primary": "#2b2b2b",
        "background": "#e0e0e0",
        "accent": "#b3b3b3",
        "secondary": "#848484",
    },
    "red": {
        "primary": "#cc0000",
        "background": "#fdfbf2",
        "accent": "#ff5722",
        "secondary": "#e60000",
    },
    "pink": {
        "primary": "#c2185b",
        "background": "#fce4ec",
        "accent": "#f48fb1",
        "secondary": "#e91e63",
    },
    "green": {
        "primary": "#33691e",
        "background": "#f1f8e9",
        "accent": "#9acd32",
        "secondary": "#558b2f",
    },
    "blue": {
        "primary": "#092c56",
        "background": "#f0f5f4",
        "accent": "#2196f3",
        "secondary": "#225688",
    },
    "purple": {
        "primary": "#312a44",
        "background": "#dad4df",
        "accent": "#8870e3",
        "secondary": "#5b4b8a",
    },
    "orange": {
        "primary": "#c24100",
        "background": "#fff8f0",
        "accent": "#ff7b00",
        "secondary": "#9a3412",
    },
    "yellow": {
        "primary": "#7a6200",
        "background": "#fdfbcf",
        "accent": "#f7c319",
        "secondary": "#8a6d00",
    },
    "carmelita": {
        "primary": "#5e3023",
        "background": "#f3e9dc",
        "accent": "#c08552",
        "secondary": "#895737",
    },
}


class PaletteColor(TypedDict):
    hex: str
    opacity: int


CatalogPalette = dict[str, PaletteColor]


def _coerce_catalog_theme(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def parse_catalog_theme(value: str) -> CatalogTheme:
    theme = _coerce_catalog_theme(value)
    if theme not in CATALOG_THEMES:
        options = ", ".join(CATALOG_THEMES)
        raise ValueError(f"Tema no válido. Opciones: {options}")
    return theme  # type: ignore[return-value]


def normalize_catalog_theme(value: str | None) -> CatalogTheme:
    theme = _coerce_catalog_theme(value)
    if theme in CATALOG_THEMES:
        return theme  # type: ignore[return-value]
    return DEFAULT_CATALOG_THEME


def parse_hex_color(value: Any) -> str:
    raw = str(value or "").strip()
    match = _HEX_RE.fullmatch(raw)
    if not match:
        raise ValueError("El color debe ser un hex de 6 dígitos, por ejemplo #59802c.")
    return f"#{match.group(1).lower()}"


def parse_opacity(value: Any) -> int:
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError("La opacidad debe ser un número entre 0 y 100.") from exc
    return max(0, min(100, amount))


def palette_from_theme(theme: str | None) -> CatalogPalette:
    tokens = THEME_TOKENS[normalize_catalog_theme(theme)]
    return {
        slot: {"hex": tokens[slot], "opacity": 100}
        for slot in PALETTE_SLOTS
    }


def _parse_palette_slot(raw: Any, fallback: PaletteColor) -> PaletteColor:
    if not isinstance(raw, dict):
        return {"hex": fallback["hex"], "opacity": fallback["opacity"]}
    hex_value = fallback["hex"]
    if raw.get("hex") not in (None, ""):
        hex_value = parse_hex_color(raw.get("hex"))
    opacity = fallback["opacity"]
    if raw.get("opacity") is not None and raw.get("opacity") != "":
        opacity = parse_opacity(raw.get("opacity"))
    return {"hex": hex_value, "opacity": opacity}


def parse_catalog_palette(value: Any, theme: str | None = None) -> CatalogPalette:
    fallback = palette_from_theme(theme)
    if value is None:
        return fallback
    if not isinstance(value, dict):
        raise ValueError("La paleta de colores no es válida.")
    return {slot: _parse_palette_slot(value.get(slot), fallback[slot]) for slot in PALETTE_SLOTS}


def normalize_catalog_palette(value: Any, theme: str | None = None) -> CatalogPalette | None:
    if value is None or value == "":
        return None
    try:
        return parse_catalog_palette(value, theme)
    except ValueError:
        return None


def public_catalog_palette(value: Any, theme: str | None = None) -> CatalogPalette | None:
    parsed = normalize_catalog_palette(value, theme)
    if parsed is None:
        return palette_from_theme(theme)
    return parsed


REVOLICO_PRODUCT_CATEGORIES: list[dict[str, Any]] = [
    {"id": "electrodomesticos", "name": "Electrodomésticos", "sort_order": 1},
    {"id": "electronica", "name": "Electrónica", "sort_order": 2},
    {"id": "computadoras-celulares", "name": "Computadoras y Celulares", "sort_order": 3},
    {"id": "ropa-zapato-accesorios", "name": "Ropa, Zapato y Accesorios", "sort_order": 4},
    {"id": "muebles-decoracion", "name": "Muebles y Decoración", "sort_order": 5},
    {"id": "construccion-herramientas", "name": "Construcción y Herramientas", "sort_order": 6},
    {"id": "alimentos", "name": "Alimentos", "sort_order": 7},
    {"id": "salud-belleza", "name": "Salud y Belleza", "sort_order": 8},
    {"id": "deportes-recreacion", "name": "Deportes y Recreación", "sort_order": 9},
    {"id": "mascotas", "name": "Mascotas", "sort_order": 10},
    {"id": "bebes-ninos", "name": "Bebés y Niños", "sort_order": 11},
    {"id": "juguetes", "name": "Juguetes", "sort_order": 12},
    {"id": "arte-antiguedades", "name": "Arte y Antigüedades", "sort_order": 13},
    {"id": "jardin-agricultura", "name": "Jardín y Agricultura", "sort_order": 14},
    {"id": "libros-musica", "name": "Libros y Música", "sort_order": 15},
    {"id": "vehiculos-repuestos", "name": "Vehículos y Repuestos", "sort_order": 16},
    {"id": "otros", "name": "Otros", "sort_order": 99},
]

_CATEGORY_BY_ID = {item["id"]: item for item in REVOLICO_PRODUCT_CATEGORIES}

_LOCAL_NAME_TO_BUSINESS_CATEGORY = {
    "ferreteria": "construccion",
    "ferretería": "construccion",
    "construccion": "construccion",
    "construcción": "construccion",
    "herramientas": "construccion",
    "materiales y herramientas de construcción": "construccion",
    "materiales y herramientas de construccion": "construccion",
    "despensa": "comida",
    "alimentos": "comida",
    "comida": "comida",
    "restaurant": "restaurant",
    "restaurante": "restaurant",
    "cafeteria": "restaurant",
    "cafetería": "restaurant",
    "ropa": "moda",
    "moda": "moda",
    "muebles": "hogar",
    "decoracion": "hogar",
    "decoración": "hogar",
    "hogar": "hogar",
    "tecnologia": "tecnologia",
    "tecnología": "tecnologia",
    "celulares": "tecnologia",
    "computadoras": "tecnologia",
    "electrodomesticos": "hogar",
    "electrodomésticos": "hogar",
    "electronica": "tecnologia",
    "electrónica": "tecnologia",
    "belleza": "belleza",
    "salud": "salud",
    "artesania": "artesanias",
    "artesanía": "artesanias",
    "artesanias": "artesanias",
    "artesanías": "artesanias",
    "vehiculos": "medios-transporte",
    "vehículos": "medios-transporte",
    "vehiculos-repuestos": "medios-transporte",
    "transporte": "medios-transporte",
    "medios de transporte": "medios-transporte",
    "medios-transporte": "medios-transporte",
    "autos": "medios-transporte",
    "motos": "medios-transporte",
    "servicios": "servicios",
    "otros": "otros",
}


def map_local_category_name_to_business_category(name: str | None) -> str:
    if not name:
        return "otros"
    normalized = name.strip().lower()
    return _LOCAL_NAME_TO_BUSINESS_CATEGORY.get(normalized, "otros")


def map_seller_category_name(name: str | None) -> str:
    return map_local_category_name_to_business_category(name)


def document_to_category(doc: dict[str, Any]) -> CategoryPublic:
    return CategoryPublic(id=doc["id"], name=doc["name"])


def category_name(category_id: str) -> str:
    return _CATEGORY_BY_ID.get(category_id, {}).get("name", "Otros")


def category_sort_order(category_id: str) -> int:
    return int(_CATEGORY_BY_ID.get(category_id, {}).get("sort_order", 99))


async def ensure_product_category_seed() -> None:
    collection = get_product_categories_collection()
    await collection.create_index("id", unique=True)
    for category in REVOLICO_PRODUCT_CATEGORIES:
        await collection.update_one(
            {"id": category["id"]},
            {"$set": category},
            upsert=True,
        )


async def list_product_categories() -> list[CategoryPublic]:
    collection = get_product_categories_collection()
    cursor = collection.find({}).sort("sort_order", 1)
    documents = await cursor.to_list(length=200)
    return [document_to_category(doc) for doc in documents]


async def validate_product_category_id(category_id: str) -> str:
    normalized = category_id.strip().lower()
    if normalized not in _CATEGORY_BY_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La categoría del producto no es válida.",
        )
    return normalized


_MISSING_CATALOG_THEME_FILTER = {
    "$or": [
        {"catalog_theme": {"$exists": False}},
        {"catalog_theme": None},
        {"catalog_theme": ""},
    ]
}


async def ensure_catalog_theme_defaults_on_startup() -> int:
    """Persiste tema clásico en tiendas legacy sin catalog_theme."""
    collection = get_registrations_collection()
    result = await collection.update_many(
        _MISSING_CATALOG_THEME_FILTER,
        {"$set": {"catalog_theme": DEFAULT_CATALOG_THEME}},
    )
    if result.modified_count:
        logger.info(
            "Catálogo: tema por defecto asignado a %s tienda(s) sin catalog_theme.",
            result.modified_count,
        )
    return result.modified_count


async def get_seller_catalog_theme(seller_id: str) -> str:
    from app.services.seller_profile import _get_seller_doc

    doc = await _get_seller_doc(seller_id)
    return normalize_catalog_theme(doc.get("catalog_theme"))


async def update_seller_catalog_theme(
    seller_id: str,
    theme: str,
    palette: dict | None = None,
) -> dict:
    from app.services.seller_profile import _get_seller_doc
    from app.subscriptions.service import (
        CATALOG_THEME_PLAN_REQUIRED_MESSAGE,
        seller_has_full_store_customization,
    )

    doc = await _get_seller_doc(seller_id)
    next_theme = parse_catalog_theme(theme)
    customizing = next_theme != DEFAULT_CATALOG_THEME or palette is not None
    if customizing and not seller_has_full_store_customization(doc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CATALOG_THEME_PLAN_REQUIRED_MESSAGE,
        )
    next_palette = parse_catalog_palette(palette, next_theme)
    now = to_utc_naive(utc_now())

    collection = get_registrations_collection()
    result = await collection.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "catalog_theme": next_theme,
                "catalog_palette": next_palette,
                "updated_at": now,
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        )
    return {"catalog_theme": next_theme, "catalog_palette": next_palette}


async def update_seller_catalog_theme_profile(seller_id: str, theme: str, palette: dict | None = None):
    from app.services.seller_profile import _get_seller_doc, document_to_seller

    await update_seller_catalog_theme(seller_id, theme, palette)
    doc = await _get_seller_doc(seller_id)
    return document_to_seller(doc)
