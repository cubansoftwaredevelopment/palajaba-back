"""Datos y consultas del e2e de tema y paleta del catálogo."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.database import get_registrations_collection
from app.services.catalog_theme import PALETTE_SLOTS, palette_from_theme
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import seller_auth_headers
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "catalog_theme_e2e_v1"


def store_name(plan_tier: str, seller_id: str) -> str:
    return f"TEST Tema {plan_tier} {seller_id}"


def store_slug(plan_tier: str, seller_id: str) -> str:
    return f"test-tema-{plan_tier}-{seller_id}"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(*, seller_id: ObjectId, plan_tier: str) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name(plan_tier, str(seller_id)),
        "store_slug": store_slug(plan_tier, str(seller_id)),
        "transfer_id": f"TEST-THEME-{seller_id}",
        "phone": _unique_phone(seller_id),
        "billing_period": "monthly",
        "plan_tier": plan_tier,
        "is_trial": False,
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["otros"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "catalog_theme": "default",
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "created_at": now,
        "updated_at": now,
        "catalog_theme_e2e_marker": MARKER,
    }


def theme_update_payload(*, theme: str, primary_hex: str, primary_opacity: int) -> dict:
    palette = palette_from_theme(theme)
    palette["primary"] = {"hex": primary_hex, "opacity": primary_opacity}
    return {
        "catalog_theme": theme,
        "catalog_palette": {slot: palette[slot] for slot in PALETTE_SLOTS},
    }


async def cleanup() -> None:
    await get_registrations_collection().delete_many({"catalog_theme_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller(plan_tier: str) -> dict[str, str]:
    seller_id = ObjectId()
    await get_registrations_collection().insert_one(
        seller_document(seller_id=seller_id, plan_tier=plan_tier)
    )
    return {
        "seller_id": str(seller_id),
        "store_name": store_name(plan_tier, str(seller_id)),
        "store_slug": store_slug(plan_tier, str(seller_id)),
        "plan_tier": plan_tier,
    }


def seed_seller(plan_tier: str) -> dict[str, str]:
    return run_db(lambda: _seed_seller(plan_tier))


async def _load_seller(seller_id: str) -> dict:
    doc = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    assert doc is not None
    return doc


def load_seller(seller_id: str) -> dict:
    return run_db(lambda: _load_seller(seller_id))


def headers_for(seller: dict[str, str]) -> dict[str, str]:
    return seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
