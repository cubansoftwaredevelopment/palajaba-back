"""Datos, lecturas y limpieza del E2E de categorías."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.database import (
    get_categories_collection,
    get_product_categories_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "categories_e2e_v1"


def cleanup_db() -> None:
    async def work() -> None:
        await get_registrations_collection().delete_many({"categories_e2e_marker": MARKER})

    run_db(work)


def seed_seller() -> dict[str, str]:
    seller_id = ObjectId()

    async def work() -> dict[str, str]:
        now = to_utc_naive(utc_now())
        await get_registrations_collection().insert_one(
            {
                "_id": seller_id,
                "status": "approved",
                "store_name": f"TEST Categorias {seller_id}",
                "store_slug": f"test-categorias-{seller_id}",
                "transfer_id": f"TEST-CAT-{seller_id}",
                "phone": f"{int(str(seller_id), 16) % 100000000:08d}",
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
                "categories_e2e_marker": MARKER,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {"seller_id": str(seller_id), "store_name": f"TEST Categorias {seller_id}"}

    return run_db(work)


def load_category_documents() -> tuple[dict[str, str], list[str]]:
    async def work() -> tuple[dict[str, str], list[str]]:
        business = {
            doc["id"]: doc["name"]
            async for doc in get_categories_collection().find({}, projection={"id": 1, "name": 1})
        }
        products = [
            doc["id"]
            async for doc in get_product_categories_collection()
            .find({}, projection={"id": 1})
            .sort("sort_order", 1)
        ]
        return business, products

    return run_db(work)
