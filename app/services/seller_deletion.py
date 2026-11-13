"""Eliminación de tiendas: soft-delete admin y hard-delete self-service."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.catalogs.media_storage import remove_image
from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_disputes_collection,
    get_gestores_collection,
    get_notifications_collection,
    get_orders_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
    get_seller_contact_otp_challenges_collection,
    get_seller_devices_collection,
    get_seller_feedback_collection,
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


async def _assert_seller_account_can_be_deleted(seller_id: str) -> None:
    pending = await get_orders_collection().count_documents(
        {"seller_id": seller_id, "status": "pending_confirmation"}
    )
    if pending:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar la cuenta mientras tengas pedidos pendientes de confirmación.",
        )

    open_disputes = await get_disputes_collection().count_documents(
        {"seller_id": seller_id, "status": "open"}
    )
    if open_disputes:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar la cuenta mientras tengas disputas abiertas.",
        )

    open_qvapay = await get_orders_collection().count_documents(
        {
            "seller_id": seller_id,
            "payment_method": "qvapay",
            "status": {"$nin": ["completed", "cancelled"]},
        }
    )
    if open_qvapay:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar la cuenta mientras tengas pagos QvaPay en curso.",
        )


async def _remove_media_urls(urls: list[str | None]) -> None:
    seen: set[str] = set()
    for url in urls:
        value = str(url or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        await remove_image(value)


async def hard_delete_seller_account(seller_id: str) -> dict[str, str]:
    """Borra físicamente la cuenta y datos de tienda. Conserva pedidos."""
    await _assert_seller_account_can_be_deleted(seller_id)
    try:
        seller_oid = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Tienda no encontrada.") from exc

    collection = get_registrations_collection()
    doc = await collection.find_one({"_id": seller_oid})
    if not doc or doc.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Tienda no encontrada.")

    store_name = doc.get("store_name") or ""
    media_urls: list[str | None] = [doc.get("profile_photo_url")]
    for banner in doc.get("store_banners") or []:
        if isinstance(banner, dict):
            media_urls.append(banner.get("image_url"))

    products = await get_catalog_products_collection().find(
        {"seller_id": seller_id},
        {"image_url": 1, "image_public_id": 1, "images": 1},
    ).to_list(length=None)
    for product in products:
        media_urls.append(product.get("image_url"))
        for image in product.get("images") or []:
            if isinstance(image, dict):
                media_urls.append(image.get("image_url"))

    await get_catalog_products_collection().delete_many({"seller_id": seller_id})
    await get_catalog_categories_collection().delete_many({"seller_id": seller_id})
    await get_seller_profile_views_collection().delete_many({"seller_id": seller_id})
    await get_product_popularity_events_collection().delete_many({"seller_id": seller_id})
    await get_gestores_collection().delete_many({"seller_id": seller_oid})
    await get_gestores_collection().delete_many({"seller_id": seller_id})
    await get_notifications_collection().delete_many({"seller_id": seller_oid})
    await get_seller_devices_collection().delete_many({"seller_id": seller_oid})
    await get_seller_feedback_collection().delete_many({"seller_id": seller_oid})
    await get_seller_feedback_collection().delete_many({"seller_id": seller_id})
    await get_seller_contact_otp_challenges_collection().delete_many({"seller_id": seller_id})

    await collection.delete_one({"_id": seller_oid})
    await _remove_media_urls(media_urls)

    return {
        "id": seller_id,
        "store_name": store_name,
        "message": f"Tienda «{store_name}» eliminada.",
    }
