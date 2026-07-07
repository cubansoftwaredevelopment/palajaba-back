from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "seller_stats_revenue_totals_v1"
STORE_NAME_A = "TEST Stats Seller A"
STORE_NAME_B = "TEST Stats Seller B"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(
    *,
    seller_id: ObjectId | None = None,
    store_name: str = STORE_NAME_A,
    plan_tier: str = "premium",
) -> dict:
    now = to_utc_naive(utc_now())
    oid = seller_id or ObjectId()
    return {
        "_id": oid,
        "status": "approved",
        "store_name": store_name,
        "store_slug": f"test-stats-{oid}",
        "transfer_id": f"TEST-STATS-{oid}",
        "phone": _unique_phone(oid),
        "billing_period": "monthly",
        "plan_tier": plan_tier,
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=90),
        "subscription_ends_at": now + timedelta(days=30),
        "approved_at": datetime(2026, 1, 15, 10, 0, 0),
        "created_at": now - timedelta(days=90),
        "updated_at": now,
        "seller_stats_revenue_totals_marker": MARKER,
    }


def completed_order_document(
    *,
    seller_id: str,
    store_name: str,
    payment_currency: str,
    collected_total: float,
    completed_at: datetime,
    with_delivery: bool = False,
) -> dict:
    now = to_utc_naive(utc_now())
    items = [
        {
            "product_id": "prod-1",
            "name": "Producto test",
            "quantity": 2,
            "unit_price": collected_total / 2,
            "currency": payment_currency,
            "line_total": collected_total,
        }
    ]
    doc = {
        "seller_id": seller_id,
        "store_name": store_name,
        "status": "completed",
        "items": items,
        "subtotals": [{"currency": payment_currency, "amount": collected_total}],
        "delivery_requested": with_delivery,
        "delivery": None,
        "delivery_price": 50.0 if with_delivery else None,
        "delivery_currency": "CUP" if with_delivery else None,
        "payment_currency": payment_currency,
        "collected_total": collected_total,
        "buyer_zone": None,
        "created_at": completed_at - timedelta(hours=2),
        "updated_at": completed_at,
        "completed_at": to_utc_naive(completed_at),
        "seller_stats_revenue_totals_marker": MARKER,
    }
    return doc
