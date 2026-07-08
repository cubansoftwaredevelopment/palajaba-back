from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "seller_manual_orders_test_v1"
STORE_NAME_A = "TEST Manual Orders Seller A"
STORE_NAME_B = "TEST Manual Orders Seller B"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(
    *,
    seller_id: ObjectId | None = None,
    store_name: str = STORE_NAME_A,
) -> dict:
    now = to_utc_naive(utc_now())
    oid = seller_id or ObjectId()
    return {
        "_id": oid,
        "status": "approved",
        "store_name": store_name,
        "store_slug": f"test-manual-orders-{oid}",
        "transfer_id": f"TEST-MANUAL-{oid}",
        "phone": _unique_phone(oid),
        "billing_period": "monthly",
        "plan_tier": "premium",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=30),
        "subscription_ends_at": now + timedelta(days=30),
        "approved_at": now - timedelta(days=30),
        "created_at": now,
        "updated_at": now,
        "seller_manual_orders_test_marker": MARKER,
    }


def category_document(*, seller_id: str, category_id: ObjectId | None = None) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": category_id or ObjectId(),
        "seller_id": seller_id,
        "name": "Despensa",
        "product_count": 0,
        "sort_order": 0,
        "created_at": now,
        "updated_at": now,
        "seller_manual_orders_test_marker": MARKER,
    }


def product_document(
    *,
    seller_id: str,
    category_id: ObjectId,
    name: str,
    base_price: float = 100.0,
    stock_quantity: int | None = None,
) -> dict:
    now = to_utc_naive(utc_now())
    doc = {
        "seller_id": seller_id,
        "category_id": category_id,
        "global_category_id": "otros",
        "name": name,
        "description": "Producto de prueba",
        "image_url": "https://example.com/product.jpg",
        "base_price": base_price,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": True,
        "is_available": True,
        "view_only": False,
        "popularity": 0,
        "sort_order": 0,
        "created_at": now,
        "updated_at": now,
        "seller_manual_orders_test_marker": MARKER,
    }
    if stock_quantity is not None:
        doc["stock_quantity"] = stock_quantity
    return doc


def manual_order_payload(*, product_id: str, quantity: int = 1, unit_price: float = 100.0) -> dict:
    return {
        "items": [
            {
                "product_id": product_id,
                "name": "Producto con stock",
                "quantity": quantity,
                "unit_price": unit_price,
                "currency": "CUP",
            }
        ],
        "payment_currency": "CUP",
    }
