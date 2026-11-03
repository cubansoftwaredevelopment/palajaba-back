"""Datos del e2e de páginas de servicio al cliente."""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO

from bson import ObjectId

from app.database import get_registrations_collection
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import seller_auth_headers
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "store_pages_e2e_v1"
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc00000000300010005fed4ef0000000049454e44ae426082"
)


def store_name(seller_id: str) -> str:
    return f"TEST Paginas {seller_id}"


def store_slug(seller_id: str) -> str:
    return f"test-paginas-{seller_id}"


def photo_upload() -> tuple[str, BytesIO, str]:
    return ("foto.png", BytesIO(TINY_PNG), "image/png")


async def cleanup() -> None:
    await get_registrations_collection().delete_many({"store_pages_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller() -> dict[str, str]:
    seller_id = ObjectId()
    now = to_utc_naive(utc_now())
    await get_registrations_collection().insert_one(
        {
            "_id": seller_id,
            "status": "approved",
            "store_name": store_name(str(seller_id)),
            "store_slug": store_slug(str(seller_id)),
            "transfer_id": f"TEST-PAGES-{seller_id}",
            "phone": f"{int(str(seller_id), 16) % 100000000:08d}",
            "billing_period": "monthly",
            "plan_tier": "standard",
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
            "subscription_starts_at": now - timedelta(days=3),
            "subscription_ends_at": now + timedelta(days=27),
            "created_at": now,
            "updated_at": now,
            "store_pages_e2e_marker": MARKER,
        }
    )
    return {
        "seller_id": str(seller_id),
        "store_name": store_name(str(seller_id)),
        "store_slug": store_slug(str(seller_id)),
    }


def seed_seller() -> dict[str, str]:
    return run_db(_seed_seller)


def headers_for(seller: dict[str, str]) -> dict[str, str]:
    return seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])


async def _load_seller(seller_id: str) -> dict:
    doc = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    if doc is None:
        raise AssertionError("La tienda de prueba no está en Mongo.")
    return doc


def load_seller(seller_id: str) -> dict:
    return run_db(lambda: _load_seller(seller_id))
