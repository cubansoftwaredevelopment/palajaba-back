"""Eliminación en cascada de una tienda/vendedor y todos sus datos relacionados."""

from __future__ import annotations

import logging
from typing import Any

from bson import ObjectId

from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_notifications_collection,
    get_orders_collection,
    get_registrations_collection,
    get_seller_profile_views_collection,
)
from app.services.media_storage import remove_image

logger = logging.getLogger(__name__)


async def _remove_product_images(products: list[dict[str, Any]]) -> None:
    for product in products:
        try:
            await remove_image(
                product.get("image_url"),
                public_id=product.get("image_public_id"),
            )
        except Exception:
            logger.exception(
                "No se pudo eliminar la imagen del producto %s",
                product.get("_id"),
            )


async def delete_seller_data(seller_id: str, registration_doc: dict[str, Any]) -> None:
    """Borra catálogo, pedidos, notificaciones, vistas y medios del vendedor."""
    products_col = get_catalog_products_collection()
    categories_col = get_catalog_categories_collection()
    orders_col = get_orders_collection()
    notifications_col = get_notifications_collection()
    profile_views_col = get_seller_profile_views_collection()

    product_docs = await products_col.find({"seller_id": seller_id}).to_list(length=None)
    await _remove_product_images(product_docs)
    await products_col.delete_many({"seller_id": seller_id})
    await categories_col.delete_many({"seller_id": seller_id})
    await orders_col.delete_many({"seller_id": seller_id})

    try:
        seller_oid = ObjectId(seller_id)
    except Exception:
        seller_oid = None

    if seller_oid is not None:
        await notifications_col.delete_many({"seller_id": seller_oid})

    await profile_views_col.delete_many({"seller_id": seller_id})

    profile_photo_url = registration_doc.get("profile_photo_url")
    if profile_photo_url:
        try:
            await remove_image(profile_photo_url)
        except Exception:
            logger.exception(
                "No se pudo eliminar la foto de perfil del vendedor %s",
                seller_id,
            )


async def delete_registration_document(registration_id: str) -> dict[str, str]:
    from app.services.launch_promo import ensure_launch_promo_state
    from app.services.registrations import _get_document_or_404

    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)
    seller_id = str(doc["_id"])
    store_name = doc.get("store_name") or ""
    was_launch_promo = bool(doc.get("is_launch_promo"))

    await delete_seller_data(seller_id, doc)
    await collection.delete_one({"_id": doc["_id"]})

    if was_launch_promo:
        await ensure_launch_promo_state()

    return {
        "id": seller_id,
        "store_name": store_name,
        "message": f"Tienda «{store_name}» eliminada.",
    }
