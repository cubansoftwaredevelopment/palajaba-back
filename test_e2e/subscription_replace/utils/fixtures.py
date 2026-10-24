"""Datos y consultas del e2e de reemplazo de suscripción y gestores."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.database import get_gestores_collection, get_registrations_collection
from app.services.gestores import build_gestor_document
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "subscription_replace_e2e_v1"


def store_name(seller_id: str) -> str:
    return f"TEST Suscripcion {seller_id}"


def store_slug(seller_id: str) -> str:
    return f"test-suscripcion-{seller_id}"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(*, seller_id: ObjectId, plan_tier: str, is_trial: bool = False) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name(str(seller_id)),
        "store_slug": store_slug(str(seller_id)),
        "transfer_id": f"TEST-SUB-{seller_id}",
        "phone": _unique_phone(seller_id),
        "billing_period": "yearly",
        "plan_tier": plan_tier,
        "is_trial": is_trial,
        "gestores_enabled": True,
        "checkout_include_store_phone": False,
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["otros"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=10),
        "subscription_ends_at": now + timedelta(days=355),
        "created_at": now,
        "updated_at": now,
        "subscription_replace_e2e_marker": MARKER,
    }


async def cleanup() -> None:
    registrations = get_registrations_collection()
    seller_oids = [
        doc["_id"]
        async for doc in registrations.find({"subscription_replace_e2e_marker": MARKER}, {"_id": 1})
    ]
    if seller_oids:
        await get_gestores_collection().delete_many({"seller_id": {"$in": seller_oids}})
    await registrations.delete_many({"subscription_replace_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller_with_gestores(
    *,
    plan_tier: str,
    gestor_count: int,
    is_trial: bool = False,
) -> dict:
    seller_id = ObjectId()
    docs = [build_gestor_document(seller_id=seller_id, username=f"gestor{i}") for i in range(gestor_count)]
    if docs:
        result = await get_gestores_collection().insert_many(docs)
        gestor_ids = [str(oid) for oid in result.inserted_ids]
    else:
        gestor_ids = []
    seller = seller_document(seller_id=seller_id, plan_tier=plan_tier, is_trial=is_trial)
    seller["checkout_gestor_ids"] = list(gestor_ids)
    await get_registrations_collection().insert_one(seller)
    return {
        "seller_id": str(seller_id),
        "store_name": store_name(str(seller_id)),
        "gestor_ids": gestor_ids,
    }


def seed_seller_with_gestores(
    *,
    plan_tier: str,
    gestor_count: int,
    is_trial: bool = False,
) -> dict:
    return run_db(
        lambda: _seed_seller_with_gestores(
            plan_tier=plan_tier,
            gestor_count=gestor_count,
            is_trial=is_trial,
        )
    )


async def _load_seller_and_gestores(seller_id: str) -> tuple[dict, list[dict]]:
    seller = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    assert seller is not None
    gestores = (
        await get_gestores_collection()
        .find({"seller_id": ObjectId(seller_id)})
        .sort("username", 1)
        .to_list(length=None)
    )
    return seller, gestores


def load_seller_and_gestores(seller_id: str) -> tuple[dict, list[dict]]:
    return run_db(lambda: _load_seller_and_gestores(seller_id))
