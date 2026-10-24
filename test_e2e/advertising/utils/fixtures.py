"""Datos y limpieza del e2e de publicidad / QvaPay."""

from __future__ import annotations

from app.database import (
    get_advertising_purchases_collection,
    get_finance_ledger_collection,
    get_platform_settings_collection,
)
from test_e2e.products.utils.fixtures import seed_seller as seed_product_seller
from test_e2e.utils.database import run_db


async def cleanup() -> None:
    await get_advertising_purchases_collection().delete_many({})
    await get_finance_ledger_collection().delete_many({"source": "advertising", "reason": {"$regex": "e2e|"}})
    await get_finance_ledger_collection().delete_many({"source": "advertising"})


def cleanup_db() -> None:
    run_db(cleanup)


def seed_seller() -> dict[str, str]:
    return seed_product_seller(plan_tier="standard")


async def seed_admin_contact() -> None:
    from app.services.platform_settings import SETTINGS_ID
    from app.utils.datetime import to_utc_naive, utc_now

    now = to_utc_naive(utc_now())
    await get_platform_settings_collection().update_one(
        {"_id": SETTINGS_ID},
        {
            "$set": {
                "admins": [
                    {"email": "admin.ads.e2e@palajaba.test", "phone": "+5355511122"},
                    {"email": "ops.ads.e2e@palajaba.test", "phone": "+5355511133"},
                ],
                "admin_email": "admin.ads.e2e@palajaba.test",
                "admin_phone": "+5355511122",
                "updated_at": now,
            },
            "$setOnInsert": {"_id": SETTINGS_ID, "created_at": now},
        },
        upsert=True,
    )


def seed_admin_contact_db() -> None:
    run_db(seed_admin_contact)
