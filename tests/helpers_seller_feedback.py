from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.utils.datetime import to_utc_naive, utc_now

MARKER = "seller_feedback_test_v1"
STORE_NAME = "TEST Seller Feedback Store"
STORE_SLUG = "test-seller-feedback-store"
COMPLAINT_MESSAGE = "Queja de prueba con suficientes caracteres."
SUGGESTION_MESSAGE = "Sugerencia de prueba con suficientes caracteres."


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
        "transfer_id": f"TEST-FEEDBACK-{MARKER}",
        "phone": _unique_phone(oid),
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": "la-habana",
            "province_name": "La Habana",
            "municipality_id": "playa",
            "municipality_name": "Playa",
        },
        "delivery_areas": [],
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "seller_feedback_test_marker": MARKER,
    }


def feedback_document(
    *,
    seller_id: ObjectId,
    feedback_type: str = "suggestion",
    message: str = SUGGESTION_MESSAGE,
    read_at=None,
    feedback_id: ObjectId | None = None,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": feedback_id or ObjectId(),
        "seller_id": seller_id,
        "store_name": STORE_NAME,
        "store_slug": STORE_SLUG,
        "feedback_type": feedback_type,
        "message": message,
        "read_at": read_at,
        "created_at": now,
        "seller_feedback_test_marker": MARKER,
    }
