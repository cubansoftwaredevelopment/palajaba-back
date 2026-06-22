from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers import (
    PROVINCE_ID,
    REMOTE_MUNICIPALITY_ID,
    SELLER_MUNICIPALITY_ID,
)

MARKER = "store_catalog_test_v1"
STORE_SLUG = "test-store-catalog-bug"
STORE_NAME = "TEST Store Catalog Bug"
STORE_SLUG_PICKUP_ONLY = "test-store-pickup-only"
STORE_NAME_PICKUP_ONLY = "TEST Store Pickup Only"
STORE_SLUG_NO_CATEGORIES = "test-store-no-categories"
STORE_NAME_NO_CATEGORIES = "TEST Store No Categories"
STORE_SLUG_ORPHAN = "test-store-orphan-category"
STORE_NAME_ORPHAN = "TEST Store Orphan Category"

PRODUCT_VIEW_ONLY = "SC view only"
PRODUCT_PICKUP_ONLY = "SC pickup only"
PRODUCT_WITH_DELIVERY = "SC with delivery"
PRODUCT_UNAVAILABLE = "SC unavailable"
PRODUCT_VIEW_ONLY_UNAVAILABLE = "SC view only unavailable"
PRODUCT_ORPHAN = "SC orphan category"
PRODUCT_NO_OFFERS_FIELD = "SC missing offers_delivery field"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(
    *,
    seller_id: ObjectId | None = None,
    store_name: str = STORE_NAME,
    store_slug: str = STORE_SLUG,
    municipality_id: str = SELLER_MUNICIPALITY_ID,
    offers_delivery: bool = True,
    delivery_to_remote: bool = True,
) -> dict:
    now = to_utc_naive(utc_now())
    oid = seller_id or ObjectId()
    doc = {
        "_id": oid,
        "status": "approved",
        "store_name": store_name,
        "store_slug": store_slug,
        "transfer_id": f"TEST-SC-{store_slug}",
        "phone": _unique_phone(oid),
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": offers_delivery,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": municipality_id,
            "municipality_name": "Playa"
            if municipality_id == SELLER_MUNICIPALITY_ID
            else "Marianao",
        },
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "store_catalog_test_marker": MARKER,
    }
    if offers_delivery and delivery_to_remote:
        doc["delivery_areas"] = [
            {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": REMOTE_MUNICIPALITY_ID,
                "municipality_name": "Marianao",
            }
        ]
    else:
        doc["delivery_areas"] = []
    return doc


def category_document(
    *,
    seller_id: str,
    name: str = "Categoría principal",
    sort_order: int = 0,
    category_id: ObjectId | None = None,
) -> dict:
    return {
        "_id": category_id or ObjectId(),
        "seller_id": seller_id,
        "name": name,
        "sort_order": sort_order,
        "store_catalog_test_marker": MARKER,
    }


def product_document(
    *,
    seller_id: str,
    category_id: ObjectId | None,
    name: str,
    view_only: bool = False,
    offers_delivery: bool = True,
    is_available: bool = True,
    include_offers_delivery_field: bool = True,
    product_id: ObjectId | None = None,
) -> dict:
    now = to_utc_naive(utc_now())
    doc: dict = {
        "_id": product_id or ObjectId(),
        "seller_id": seller_id,
        "category_id": category_id,
        "name": name,
        "description": "Producto de prueba catálogo",
        "image_url": "https://example.com/product.jpg",
        "base_price": 150.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "is_available": is_available,
        "view_only": view_only,
        "global_category_id": "otros",
        "store_catalog_test_marker": MARKER,
        "created_at": now,
        "updated_at": now,
    }
    if include_offers_delivery_field:
        doc["offers_delivery"] = offers_delivery
    return doc
