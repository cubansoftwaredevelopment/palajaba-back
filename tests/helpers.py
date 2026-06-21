from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now

MARKER = "view_only_store_catalog_test_v2"
STORE_NAME = "TEST ViewOnly Store Catalog"
STORE_SLUG = "test-viewonly-store-catalog"
PROVINCE_ID = "la-habana"
SELLER_MUNICIPALITY_ID = "playa"
REMOTE_MUNICIPALITY_ID = "marianao"
PRODUCT_VIEW_ONLY = "TEST solo vista sin domicilio"
PRODUCT_PURCHASABLE_NO_DELIVERY = "TEST comprable sin domicilio"
PRODUCT_PURCHASABLE_WITH_DELIVERY = "TEST comprable con domicilio"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(seller_id: ObjectId | None = None) -> dict:
    now = to_utc_naive(utc_now())
    oid = seller_id or ObjectId()
    return {
        "_id": oid,
        "status": "approved",
        "store_name": STORE_NAME,
        "store_slug": STORE_SLUG,
        "transfer_id": f"TEST-VIEWONLY-{MARKER}",
        "phone": _unique_phone(oid),
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "delivery_areas": [
            {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": REMOTE_MUNICIPALITY_ID,
                "municipality_name": "Marianao",
            }
        ],
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
    }


def product_document(
    *,
    seller_id: str,
    category_id: ObjectId,
    name: str,
    view_only: bool,
    offers_delivery: bool,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "seller_id": seller_id,
        "category_id": category_id,
        "name": name,
        "description": "Producto de prueba",
        "image_url": "https://example.com/product.jpg",
        "base_price": 150.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": offers_delivery,
        "is_available": True,
        "view_only": view_only,
        "global_category_id": "otros",
        "view_only_store_catalog_test_marker": MARKER,
        "created_at": now,
        "updated_at": now,
    }
