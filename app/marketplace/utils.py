"""Utilidades compartidas del marketplace: zona, paginación, categorías y monedas."""

import re
from typing import Any
from bson import ObjectId
from bson.errors import InvalidId
from app.constants import (
    CURRENCY_CODES,
    MUNICIPALITIES_BY_PROVINCE,
    PROVINCE_NAMES,
)
from app.auth.profile_schemas import BusinessArea, BusinessLocation
from app.categories.service import (
    DEFAULT_CATEGORIES,
    business_category_name,
    normalize_business_category_id,
)
from app.catalogs.catalog_theme import REVOLICO_PRODUCT_CATEGORIES

KNOWN_BUSINESS_CATEGORY_IDS = {item["id"] for item in DEFAULT_CATEGORIES}

KNOWN_PRODUCT_CATEGORY_IDS = {item["id"] for item in REVOLICO_PRODUCT_CATEGORIES}

def _display_category_name(category_id: str) -> str:
    return business_category_name(category_id)

def _normalize_marketplace_category_id(category_id: str) -> str:
    normalized = category_id.strip().lower()
    if normalized in KNOWN_BUSINESS_CATEGORY_IDS or normalized in KNOWN_PRODUCT_CATEGORY_IDS:
        return normalize_business_category_id(normalized)
    raise ValueError("Categoría no válida.")

DEFAULT_PAGE_SIZE = 20

MAX_PAGE_SIZE = 50

def _validate_location_ids(province_id: str, municipality_id: str) -> tuple[str, str]:
    province_name = PROVINCE_NAMES.get(province_id)
    if not province_name:
        raise ValueError("Provincia no válida.")

    municipalities = MUNICIPALITIES_BY_PROVINCE.get(province_id, {})
    municipality_name = municipalities.get(municipality_id)
    if not municipality_name:
        raise ValueError("Municipio no válido para la provincia seleccionada.")

    return province_name, municipality_name

def _normalize_additional_municipalities(
    province_id: str,
    base_municipality_id: str,
    municipios_adicionales: list[str] | None,
) -> list[str]:
    if not municipios_adicionales:
        return []

    municipalities = MUNICIPALITIES_BY_PROVINCE.get(province_id, {})
    if not municipalities:
        raise ValueError("Provincia no válida.")

    normalized_base = base_municipality_id.strip()
    seen: set[str] = set()
    result: list[str] = []

    for raw_id in municipios_adicionales:
        municipality_id = raw_id.strip()
        if not municipality_id or municipality_id == normalized_base:
            continue
        if municipality_id not in municipalities:
            raise ValueError(
                f"Municipio adicional no válido para la provincia: {municipality_id}."
            )
        if municipality_id not in seen:
            seen.add(municipality_id)
            result.append(municipality_id)

    return result

def _selected_sales_area_municipality_ids(
    province_id: str,
    municipality_id: str,
    municipios_adicionales: list[str] | None,
) -> list[str]:
    additional = _normalize_additional_municipalities(
        province_id,
        municipality_id,
        municipios_adicionales,
    )
    return list(dict.fromkeys([municipality_id, *additional]))

def _normalize_page_size(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))

def _parse_business_area(raw: Any) -> BusinessArea | None:
    if not isinstance(raw, dict):
        return None
    required = ("province_id", "province_name", "municipality_id", "municipality_name")
    if not all(raw.get(key) for key in required):
        return None
    return BusinessArea(
        province_id=raw["province_id"],
        province_name=raw["province_name"],
        municipality_id=raw["municipality_id"],
        municipality_name=raw["municipality_name"],
    )

def _parse_delivery_areas(raw: Any) -> list[BusinessArea]:
    if not isinstance(raw, list):
        return []
    areas: list[BusinessArea] = []
    for item in raw:
        parsed = _parse_business_area(item)
        if parsed is not None:
            areas.append(parsed)
    return areas

def _parse_business_location(raw: Any) -> BusinessLocation | None:
    if not isinstance(raw, dict) or raw.get("lat") is None:
        return None
    return BusinessLocation(
        lat=raw["lat"],
        lng=raw["lng"],
        label=raw.get("label"),
    )

def _normalize_display_currencies(currency: str | list[str] | None) -> list[str] | None:
    if currency is None:
        return None
    values = currency if isinstance(currency, list) else [currency]
    codes: list[str] = []
    for raw in values:
        if raw is None:
            continue
        for part in str(raw).split(","):
            code = part.strip().upper()
            if not code:
                continue
            if code not in CURRENCY_CODES:
                raise ValueError("Moneda no válida.")
            if code not in codes:
                codes.append(code)
    return codes or None

def _normalize_display_currency(currency: str | list[str] | None) -> str | None:
    codes = _normalize_display_currencies(currency)
    return codes[0] if codes else None


# QUSD es el dólar de QvaPay y se cotiza 1 a 1 con el USD.

_DOLLAR_CURRENCIES = frozenset({"USD", "QUSD"})

def _equivalent_currencies(currencies: list[str] | None) -> list[str]:
    expanded: list[str] = []
    for code in currencies or []:
        group = _DOLLAR_CURRENCIES if code in _DOLLAR_CURRENCIES else (code,)
        for item in group:
            if item not in expanded:
                expanded.append(item)
    return expanded

def _and_match(query: dict[str, Any], clause: dict[str, Any] | None) -> dict[str, Any]:
    if not clause or query.get("_id") == {"$exists": False}:
        return query
    return {"$and": [query, clause]}

def _search_text_filter(query_text: str) -> dict[str, Any] | None:
    normalized = query_text.strip()
    if not normalized:
        return None
    pattern = re.escape(normalized)
    return {
        "$or": [
            {"name": {"$regex": pattern, "$options": "i"}},
            {"description": {"$regex": pattern, "$options": "i"}},
        ],
    }

def _base_product_filter(seller_ids: list[str]) -> dict[str, Any]:
    return {
        "seller_id": {"$in": seller_ids},
        "is_available": True,
        "view_only": {"$ne": True},
    }

def _product_currency_codes(doc: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    base = str(doc.get("base_currency") or "").strip().upper()
    if base in CURRENCY_CODES:
        codes.add(base)
    for raw in doc.get("accepted_currencies") or []:
        code = str(raw).strip().upper()
        if code in CURRENCY_CODES:
            codes.add(code)
    return codes

def _product_object_id(product_id: str) -> ObjectId:
    try:
        return ObjectId(str(product_id).strip())
    except InvalidId as exc:
        raise ValueError("Producto no encontrado.") from exc

def _listable_product_count(stats: dict[str, int] | None) -> int:
    """Productos disponibles en catálogo, incluyendo solo vista."""
    if not stats:
        return 0
    return int(stats.get("published") or 0) + int(stats.get("view_only") or 0)
