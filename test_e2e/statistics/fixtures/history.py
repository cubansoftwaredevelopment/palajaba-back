"""Tienda, pedidos completados y pago del día aislado."""

from datetime import datetime, timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.statistics.fixtures.constants import (
    CUP_COLLECTED,
    ISOLATED_DAY,
    MARKER,
    PAYMENT_CUP,
    UNCONVERTIBLE_COLLECTED,
)
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


def store_name(seller_id: ObjectId) -> str:
    return f"TEST Estadisticas {seller_id}"


def _phone(seller_id: ObjectId) -> str:
    return f"{int(str(seller_id), 16) % 100000000:08d}"


def completed_at() -> datetime:
    return datetime(ISOLATED_DAY.year, ISOLATED_DAY.month, ISOLATED_DAY.day, 15, 0)


def seller_document(seller_id: ObjectId, name: str) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": name,
        "store_slug": f"test-estadisticas-{seller_id}",
        "transfer_id": f"TEST-STATS-{seller_id}",
        "phone": _phone(seller_id),
        "billing_period": "monthly",
        "plan_tier": "basic",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["otros"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=1),
        "subscription_ends_at": now + timedelta(days=20),
        "statistics_e2e_marker": MARKER,
        "created_at": now,
        "updated_at": now,
    }


def completed_orders(seller_id: ObjectId, name: str) -> list[dict]:
    moment = completed_at()
    return [
        {
            "seller_id": str(seller_id),
            "store_name": name,
            "status": "completed",
            "completed_at": moment,
            "collected_total": amount,
            "payment_currency": currency,
            "statistics_e2e_marker": MARKER,
        }
        for currency, amount in (("CUP", CUP_COLLECTED), ("ZZZ", UNCONVERTIBLE_COLLECTED))
    ]


def payment_document() -> dict:
    return {
        "amount_cup": PAYMENT_CUP,
        "recorded_at": completed_at(),
        "statistics_e2e_marker": MARKER,
    }
