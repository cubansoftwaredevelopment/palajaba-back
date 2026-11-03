"""Marca como eliminada una tienda y los datos que le pertenecen. No borra documentos ni imágenes."""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_notifications_collection,
    get_orders_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
    get_seller_profile_views_collection,
)
from app.utils.datetime import to_utc_naive, utc_now


async def _mark_deleted(collection, query: dict[str, Any], now) -> None:
    await collection.update_many(
        {**query, "deleted_at": None},
        {"$set": {"deleted_at": now, "updated_at": now}},
    )


async def delete_seller_data(seller_id: str, registration_doc: dict[str, Any]) -> None:
    """Marca catálogo, pedidos, avisos, vistas y popularidad del vendedor."""
    _ = registration_doc
    now = to_utc_naive(utc_now())
    await _mark_deleted(get_catalog_products_collection(), {"seller_id": seller_id}, now)
    await _mark_deleted(get_catalog_categories_collection(), {"seller_id": seller_id}, now)
    await _mark_deleted(get_orders_collection(), {"seller_id": seller_id}, now)
    await _mark_deleted(get_seller_profile_views_collection(), {"seller_id": seller_id}, now)
    await _mark_deleted(get_product_popularity_events_collection(), {"seller_id": seller_id}, now)

    try:
        seller_oid = ObjectId(seller_id)
    except Exception:
        seller_oid = None
    if seller_oid is not None:
        await _mark_deleted(get_notifications_collection(), {"seller_id": seller_oid}, now)


async def delete_registration_document(registration_id: str) -> dict[str, str]:
    from app.auth.registrations import _get_document_or_404

    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)
    seller_id = str(doc["_id"])
    store_name = doc.get("store_name") or ""

    await delete_seller_data(seller_id, doc)
    now = to_utc_naive(utc_now())
    await collection.update_one(
        {"_id": doc["_id"]},
        {"$set": {"deleted_at": now, "updated_at": now}},
    )

    return {
        "id": seller_id,
        "store_name": store_name,
        "message": f"Tienda «{store_name}» eliminada.",
    }
