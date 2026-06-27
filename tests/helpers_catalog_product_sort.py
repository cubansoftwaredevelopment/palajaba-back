from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "catalog_product_sort_test_v1"
STORE_NAME = "TEST Catalog Product Sort"
STORE_SLUG = "test-catalog-product-sort"


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
        "transfer_id": f"TEST-SORT-{MARKER}",
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
        "delivery_areas": [],
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "catalog_product_sort_test_marker": MARKER,
    }


def category_document(
    *,
    seller_id: str,
    category_id: ObjectId | None = None,
    name: str = "Despensa",
    product_sort_mode: str | None = None,
) -> dict:
    now = to_utc_naive(utc_now())
    doc = {
        "_id": category_id or ObjectId(),
        "seller_id": seller_id,
        "name": name,
        "product_count": 0,
        "sort_order": 0,
        "created_at": now,
        "updated_at": now,
        "catalog_product_sort_test_marker": MARKER,
    }
    if product_sort_mode is not None:
        doc["product_sort_mode"] = product_sort_mode
    return doc


def product_document(
    *,
    seller_id: str,
    category_id: ObjectId,
    name: str,
    base_price: float,
    popularity: int = 0,
    sort_order: int = 0,
    base_currency: str = "CUP",
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "seller_id": seller_id,
        "category_id": category_id,
        "name": name,
        "description": "Producto de prueba",
        "image_url": "https://example.com/product.jpg",
        "base_price": base_price,
        "base_currency": base_currency,
        "accepted_currencies": ["CUP"],
        "offers_delivery": True,
        "is_available": True,
        "view_only": False,
        "global_category_id": "otros",
        "popularity": popularity,
        "sort_order": sort_order,
        "created_at": now,
        "updated_at": now,
        "catalog_product_sort_test_marker": MARKER,
    }
