"""Datos y consultas propios del e2e de popularidad."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.database import (
    get_catalog_products_collection,
    get_orders_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import seller_auth_headers
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "product_popularity_e2e_v1"
PRODUCT_NAME = "Producto popularidad e2e"
STALE_EVENT_POINTS = 10


def store_name(plan_tier: str, seller_id: str) -> str:
    return f"TEST Popularidad {plan_tier} {seller_id}"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(*, seller_id: ObjectId, plan_tier: str) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name(plan_tier, str(seller_id)),
        "store_slug": f"test-popularidad-{plan_tier}-{seller_id}",
        "transfer_id": f"TEST-POP-{seller_id}",
        "phone": _unique_phone(seller_id),
        "billing_period": "monthly",
        "plan_tier": plan_tier,
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": False,
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
        "product_popularity_e2e_marker": MARKER,
    }


def product_document(*, seller_id: str, product_id: ObjectId) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": product_id,
        "seller_id": seller_id,
        "category_id": ObjectId(),
        "name": PRODUCT_NAME,
        "description": "Producto de prueba",
        "image_url": "https://example.com/product.jpg",
        "base_price": 100.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": False,
        "is_available": True,
        "view_only": False,
        "global_category_id": "otros",
        "popularity": 99,
        "sort_order": 0,
        "created_at": now,
        "updated_at": now,
        "product_popularity_e2e_marker": MARKER,
    }


def order_payload(*, seller_id: str, product_id: str) -> dict:
    return {
        "store_id": seller_id,
        "items": [
            {
                "product_id": product_id,
                "name": PRODUCT_NAME,
                "quantity": 5,
                "unit_price": 100.0,
                "currency": "CUP",
            }
        ],
        "payment_currency": "CUP",
    }


async def cleanup() -> None:
    products = get_catalog_products_collection()
    registrations = get_registrations_collection()
    events = get_product_popularity_events_collection()
    orders = get_orders_collection()
    seller_ids = [
        str(doc["_id"])
        async for doc in registrations.find(
            {"product_popularity_e2e_marker": MARKER},
            {"_id": 1},
        )
    ]
    product_ids = [
        str(doc["_id"])
        async for doc in products.find(
            {"product_popularity_e2e_marker": MARKER},
            {"_id": 1},
        )
    ]
    if seller_ids:
        await orders.delete_many({"seller_id": {"$in": seller_ids}})
        await events.delete_many({"seller_id": {"$in": seller_ids}})
    if product_ids:
        await events.delete_many({"product_id": {"$in": product_ids}})
    await products.delete_many({"product_popularity_e2e_marker": MARKER})
    await registrations.delete_many({"product_popularity_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller_and_product(plan_tier: str) -> tuple[str, str]:
    seller_id = ObjectId()
    product_id = ObjectId()
    await get_registrations_collection().insert_one(
        seller_document(seller_id=seller_id, plan_tier=plan_tier)
    )
    await get_catalog_products_collection().insert_one(
        product_document(seller_id=str(seller_id), product_id=product_id)
    )
    await get_product_popularity_events_collection().insert_one(
        {
            "product_id": str(product_id),
            "seller_id": str(seller_id),
            "event": "view",
            "points": STALE_EVENT_POINTS,
            "created_at": to_utc_naive(utc_now() - timedelta(days=22)),
            "product_popularity_e2e_marker": MARKER,
        }
    )
    return str(seller_id), str(product_id)


def seed_seller_and_product(plan_tier: str) -> tuple[str, str]:
    return run_db(lambda: _seed_seller_and_product(plan_tier))


async def _load_product_and_events(product_id: str) -> tuple[dict, list[dict]]:
    product = await get_catalog_products_collection().find_one({"_id": ObjectId(product_id)})
    events = await get_product_popularity_events_collection().find(
        {"product_id": product_id}
    ).sort("created_at", 1).to_list(length=None)
    return product, events


def load_product_and_events(product_id: str) -> tuple[dict, list[dict]]:
    return run_db(lambda: _load_product_and_events(product_id))


async def _count_events(product_id: str) -> int:
    return await get_product_popularity_events_collection().count_documents(
        {"product_id": product_id}
    )


def count_events(product_id: str) -> int:
    return run_db(lambda: _count_events(product_id))


def headers_for(seller_id: str, plan_tier: str) -> dict[str, str]:
    return seller_auth_headers(
        seller_id=seller_id,
        store_name=store_name(plan_tier, seller_id),
    )
