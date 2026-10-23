from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.database import get_registrations_collection
from app.services.catalog_theme import (
    DEFAULT_CATALOG_THEME,
    normalize_catalog_theme,
    parse_catalog_palette,
    parse_catalog_theme,
)
from app.services.plans import (
    CATALOG_THEME_PLAN_REQUIRED_MESSAGE,
    seller_has_full_store_customization,
)
from app.services.seller_profile import _get_seller_doc, document_to_seller
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)

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
    doc = await _get_seller_doc(seller_id)
    return normalize_catalog_theme(doc.get("catalog_theme"))


async def update_seller_catalog_theme(
    seller_id: str,
    theme: str,
    palette: dict | None = None,
) -> dict:
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
    await update_seller_catalog_theme(seller_id, theme, palette)
    doc = await _get_seller_doc(seller_id)
    return document_to_seller(doc)
