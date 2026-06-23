from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.security import hash_password
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug

MARKER = "admin_registration_payment_test_v1"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def pending_registration_document(
    *,
    registration_id: ObjectId | None = None,
    store_name: str | None = None,
) -> dict:
    oid = registration_id or ObjectId()
    name = store_name or f"TEST Free Store {str(oid)[-6:]}"
    now = to_utc_naive(utc_now())
    return {
        "_id": oid,
        "transfer_id": f"TEST-PAY-{str(oid)}",
        "store_name": name,
        "store_slug": store_name_to_slug(name),
        "phone": _unique_phone(oid),
        "password_hash": hash_password("TestPay2026!"),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "status": "pending",
        "subscription_starts_at": None,
        "subscription_ends_at": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "approved_at": None,
        "payment_amount_cup": None,
        "profile_photo_url": None,
        "business_location": None,
        "biography": None,
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": [],
        "offers_delivery": None,
        "profile_completed_at": None,
        MARKER: True,
    }


def expired_registration_document(
    *,
    registration_id: ObjectId | None = None,
    store_name: str | None = None,
) -> dict:
    oid = registration_id or ObjectId()
    name = store_name or f"TEST Expired Store {str(oid)[-6:]}"
    now = to_utc_naive(utc_now())
    yesterday = now - timedelta(days=1)
    return {
        "_id": oid,
        "transfer_id": f"TEST-EXP-{str(oid)}",
        "store_name": name,
        "store_slug": store_name_to_slug(name),
        "phone": _unique_phone(oid),
        "password_hash": hash_password("TestPay2026!"),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "status": "expired",
        "subscription_starts_at": yesterday - timedelta(days=30),
        "subscription_ends_at": yesterday,
        "rejection_reason": None,
        "created_at": yesterday - timedelta(days=31),
        "updated_at": yesterday,
        "approved_at": yesterday - timedelta(days=30),
        "payment_amount_cup": 100,
        "profile_photo_url": None,
        "business_location": None,
        "biography": None,
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": [],
        "offers_delivery": None,
        "profile_completed_at": None,
        MARKER: True,
    }


def approved_registration_document(
    *,
    registration_id: ObjectId | None = None,
    store_name: str | None = None,
    payment_amount_cup: int = 5000,
) -> dict:
    oid = registration_id or ObjectId()
    name = store_name or f"TEST Approved Store {str(oid)[-6:]}"
    now = to_utc_naive(utc_now())
    return {
        "_id": oid,
        "transfer_id": f"TEST-APR-{str(oid)}",
        "store_name": name,
        "store_slug": store_name_to_slug(name),
        "phone": _unique_phone(oid),
        "password_hash": hash_password("TestPay2026!"),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "status": "approved",
        "subscription_starts_at": now - timedelta(days=5),
        "subscription_ends_at": now + timedelta(days=25),
        "rejection_reason": None,
        "created_at": now - timedelta(days=6),
        "updated_at": now,
        "approved_at": now - timedelta(days=5),
        "payment_amount_cup": payment_amount_cup,
        "profile_photo_url": "https://example.com/photo.jpg",
        "business_location": None,
        "biography": None,
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": ["food"],
        "offers_delivery": True,
        "profile_completed_at": None,
        MARKER: True,
    }
