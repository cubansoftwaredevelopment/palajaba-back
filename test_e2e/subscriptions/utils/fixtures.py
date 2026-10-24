"""Datos y consultas del e2e de planes y suscripciones."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.database import get_registrations_collection
from app.auth.utils import hash_password
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import seller_auth_headers
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "subscriptions_e2e_v1"
PASSWORD = "clave123"


def store_name(seller_id: str) -> str:
    return f"TEST Planes {seller_id}"


def unique_phone(seed: ObjectId) -> str:
    return f"{(int(str(seed), 16) % 90000000) + 10000000:08d}"


def seller_document(
    *,
    seller_id: ObjectId,
    plan_tier: str,
    is_trial: bool = False,
    subscription_days: int = 20,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name(str(seller_id)),
        "store_slug": f"test-planes-{seller_id}",
        "transfer_id": f"TEST-PLAN-{seller_id}",
        "phone": unique_phone(seller_id),
        "email": f"tienda.{seller_id}@subs-e2e.test",
        "password_hash": hash_password(PASSWORD),
        "billing_period": "yearly",
        "plan_tier": plan_tier,
        "is_trial": is_trial,
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["otros"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=subscription_days),
        "created_at": now,
        "updated_at": now,
        "subscriptions_e2e_marker": MARKER,
    }


async def cleanup() -> None:
    await get_registrations_collection().delete_many({"subscriptions_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller(
    *,
    plan_tier: str,
    is_trial: bool = False,
    subscription_days: int = 20,
) -> dict[str, str]:
    seller_id = ObjectId()
    doc = seller_document(
        seller_id=seller_id,
        plan_tier=plan_tier,
        is_trial=is_trial,
        subscription_days=subscription_days,
    )
    await get_registrations_collection().insert_one(doc)
    return {
        "seller_id": str(seller_id),
        "store_name": doc["store_name"],
        "phone": doc["phone"],
        "password": PASSWORD,
        "plan_tier": plan_tier,
    }


def seed_seller(
    *,
    plan_tier: str,
    is_trial: bool = False,
    subscription_days: int = 20,
) -> dict[str, str]:
    return run_db(
        lambda: _seed_seller(
            plan_tier=plan_tier,
            is_trial=is_trial,
            subscription_days=subscription_days,
        )
    )


async def _load_seller(seller_id: str) -> dict:
    doc = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    assert doc is not None
    return doc


def load_seller(seller_id: str) -> dict:
    return run_db(lambda: _load_seller(seller_id))


def headers_for(seller: dict[str, str]) -> dict[str, str]:
    return seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
