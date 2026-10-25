"""Datos y consultas del e2e de catálogo de productos."""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO

from bson import ObjectId

from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import seller_auth_headers
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import EXTRA_MUNICIPALITY_ID, PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "products_e2e_v1"
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc00000000300010005fed4ef0000000049454e44ae426082"
)


def store_name(seller_id: str) -> str:
    return f"TEST Productos {seller_id}"


def store_slug(seller_id: str) -> str:
    return f"test-productos-{seller_id}"


def unique_phone(seed: ObjectId) -> str:
    return f"{(int(str(seed), 16) % 90000000) + 10000000:08d}"


def seller_document(
    *,
    seller_id: ObjectId,
    plan_tier: str,
    is_trial: bool = False,
    extra_sales_zone: bool = False,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name(str(seller_id)),
        "store_slug": store_slug(str(seller_id)),
        "transfer_id": f"TEST-PROD-{seller_id}",
        "phone": unique_phone(seller_id),
        "billing_period": "monthly",
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
        "delivery_areas": (
            [
                {
                    "province_id": PROVINCE_ID,
                    "province_name": "La Habana",
                    "municipality_id": EXTRA_MUNICIPALITY_ID,
                    "municipality_name": "Marianao",
                }
            ]
            if extra_sales_zone
            else []
        ),
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "created_at": now,
        "updated_at": now,
        "products_e2e_marker": MARKER,
    }


async def cleanup() -> None:
    registrations = get_registrations_collection()
    seller_ids = [
        str(doc["_id"])
        async for doc in registrations.find({"products_e2e_marker": MARKER}, {"_id": 1})
    ]
    if seller_ids:
        await get_catalog_products_collection().delete_many({"seller_id": {"$in": seller_ids}})
        await get_catalog_categories_collection().delete_many({"seller_id": {"$in": seller_ids}})
    await get_catalog_products_collection().delete_many({"products_e2e_marker": MARKER})
    await get_catalog_categories_collection().delete_many({"products_e2e_marker": MARKER})
    await registrations.delete_many({"products_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller(
    *,
    plan_tier: str,
    is_trial: bool = False,
    extra_sales_zone: bool = False,
) -> dict[str, str]:
    seller_id = ObjectId()
    await get_registrations_collection().insert_one(
        seller_document(
            seller_id=seller_id,
            plan_tier=plan_tier,
            is_trial=is_trial,
            extra_sales_zone=extra_sales_zone,
        )
    )
    return {
        "seller_id": str(seller_id),
        "store_name": store_name(str(seller_id)),
        "store_slug": store_slug(str(seller_id)),
        "plan_tier": plan_tier,
    }


def seed_seller(
    *,
    plan_tier: str,
    is_trial: bool = False,
    extra_sales_zone: bool = False,
) -> dict[str, str]:
    return run_db(
        lambda: _seed_seller(
            plan_tier=plan_tier,
            is_trial=is_trial,
            extra_sales_zone=extra_sales_zone,
        )
    )


def headers_for(seller: dict[str, str]) -> dict[str, str]:
    return seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])


def product_form(
    *,
    name: str,
    category_id: str,
    base_price: float = 100,
    discount_percent: str | None = None,
    is_available: bool = True,
    offers_delivery: bool = False,
    sales_areas: str | None = None,
) -> dict[str, str]:
    payload = {
        "name": name,
        "category_id": category_id,
        "global_category_id": "otros",
        "base_price": str(base_price),
        "base_currency": "CUP",
        "offers_delivery": "true" if offers_delivery else "false",
        "accepted_currencies": '["CUP"]',
        "view_only": "false",
        "is_available": "true" if is_available else "false",
    }
    if discount_percent is not None:
        payload["discount_percent"] = discount_percent
    if sales_areas is not None:
        payload["sales_areas"] = sales_areas
    return payload


def photo_upload() -> tuple[str, BytesIO, str]:
    return ("photo.png", BytesIO(TINY_PNG), "image/png")
