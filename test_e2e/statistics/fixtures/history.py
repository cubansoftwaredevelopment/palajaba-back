"""Tienda, pedidos completados y pago del día aislado."""

from datetime import datetime, timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.statistics.fixtures.constants import (
    CUP_COLLECTED,
    ISOLATED_DAY,
    MARKER,
    PAYMENT_CUP,
    SOLD_LEAD_NAME,
    SOLD_SECOND_NAME,
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


def product_documents(seller_id: ObjectId, lead_id: ObjectId, second_id: ObjectId) -> list[dict]:
    return [
        {
            "_id": lead_id,
            "seller_id": str(seller_id),
            "name": SOLD_LEAD_NAME,
            "statistics_e2e_marker": MARKER,
        },
        {
            "_id": second_id,
            "seller_id": str(seller_id),
            "name": SOLD_SECOND_NAME,
            "statistics_e2e_marker": MARKER,
        },
    ]


def completed_orders(
    seller_id: ObjectId,
    name: str,
    lead_id: ObjectId,
    second_id: ObjectId,
) -> list[dict]:
    moment = completed_at()
    lead = str(lead_id)
    second = str(second_id)
    return [
        {
            "seller_id": str(seller_id),
            "store_name": name,
            "status": "completed",
            "completed_at": moment,
            "collected_total": CUP_COLLECTED,
            "payment_currency": "CUP",
            "items": [
                {
                    "product_id": lead,
                    "name": SOLD_LEAD_NAME,
                    "quantity": 4,
                    "unit_price": 100,
                    "currency": "CUP",
                },
                {
                    "product_id": second,
                    "name": SOLD_SECOND_NAME,
                    "quantity": 1,
                    "unit_price": 50,
                    "currency": "CUP",
                },
            ],
            "statistics_e2e_marker": MARKER,
        },
        {
            "seller_id": str(seller_id),
            "store_name": name,
            "status": "completed",
            "completed_at": moment,
            "collected_total": UNCONVERTIBLE_COLLECTED,
            "payment_currency": "ZZZ",
            "items": [
                {
                    "product_id": lead,
                    "name": SOLD_LEAD_NAME,
                    "quantity": 2,
                    "unit_price": 10,
                    "currency": "ZZZ",
                },
            ],
            "statistics_e2e_marker": MARKER,
        },
    ]


def popularity_events(seller_id: ObjectId, lead_id: ObjectId, second_id: ObjectId) -> list[dict]:
    moment = completed_at()
    seller = str(seller_id)
    return [
        {
            "product_id": str(lead_id),
            "seller_id": seller,
            "event": "view",
            "points": 1,
            "created_at": moment,
            "statistics_e2e_marker": MARKER,
        },
        {
            "product_id": str(second_id),
            "seller_id": seller,
            "event": "view",
            "points": 1,
            "created_at": moment,
            "statistics_e2e_marker": MARKER,
        },
        {
            "product_id": str(second_id),
            "seller_id": seller,
            "event": "jaba",
            "points": 2,
            "created_at": moment,
            "statistics_e2e_marker": MARKER,
        },
    ]


def payment_document() -> dict:
    return {
        "amount_cup": PAYMENT_CUP,
        "recorded_at": completed_at(),
        "statistics_e2e_marker": MARKER,
    }
