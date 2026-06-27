from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "marketplace_orders_test_v1"
STORE_NAME = "TEST Marketplace Orders"
STORE_SLUG = "test-marketplace-orders"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(*, seller_id: ObjectId | None = None) -> dict:
    now = to_utc_naive(utc_now())
    oid = seller_id or ObjectId()
    return {
        "_id": oid,
        "status": "approved",
        "store_name": STORE_NAME,
        "store_slug": STORE_SLUG,
        "transfer_id": f"TEST-ORD-{oid}",
        "phone": _unique_phone(oid),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "created_at": now,
        "updated_at": now,
        "marketplace_orders_test_marker": MARKER,
    }


def order_payload(*, store_id: str, product_id: str = "prod-1", with_delivery: bool = False) -> dict:
    payload = {
        "store_id": store_id,
        "items": [
            {
                "product_id": product_id,
                "name": "Producto test",
                "quantity": 2,
                "unit_price": 150.0,
                "currency": "CUP",
            }
        ],
        "payment_currency": "CUP",
    }
    if with_delivery:
        payload["delivery"] = {
            "recipient_name": "María López",
            "address": "Calle 10 #123",
            "phone_primary": "51234567",
            "phone_secondary": None,
            "notes": "Timbre roto",
        }
    return payload
