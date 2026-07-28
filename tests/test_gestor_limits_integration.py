from __future__ import annotations

import asyncio
import os
import unittest
from datetime import timedelta
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (  # noqa: E402
    close_mongo_connection,
    connect_to_mongo,
    get_gestores_collection,
    get_registrations_collection,
)
from app.services import gestores as gestor_service  # noqa: E402
from app.services.plans import STANDARD_GESTOR_LIMIT  # noqa: E402
from app.utils.datetime import to_utc_naive, utc_now  # noqa: E402
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID  # noqa: E402

MARKER = "gestor_limits_test_v1"
STORE_NAME = "TEST Gestor Limits Store"
STORE_SLUG = "test-gestor-limits-store"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


async def cleanup() -> None:
    await get_registrations_collection().delete_many({"gestor_limits_marker": MARKER})
    await get_gestores_collection().delete_many({"gestor_limits_marker": MARKER})


async def seed_seller(*, plan_tier: str) -> str:
    seller_oid = ObjectId()
    now = to_utc_naive(utc_now())
    await get_registrations_collection().insert_one(
        {
            "_id": seller_oid,
            "status": "approved",
            "store_name": STORE_NAME,
            "store_slug": STORE_SLUG,
            "transfer_id": f"TEST-GESTOR-LIMIT-{seller_oid}",
            "phone": f"{int(str(seller_oid), 16) % 100000000:08d}",
            "billing_period": "monthly",
            "plan_tier": plan_tier,
            "profile_photo_url": "https://example.com/photo.jpg",
            "category_ids": ["food"],
            "offers_delivery": True,
            "business_area": {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": SELLER_MUNICIPALITY_ID,
                "municipality_name": "Playa",
            },
            "gestores_enabled": True,
            "gestor_catalog_access": {"mode": "selected", "product_ids": []},
            "subscription_starts_at": now - timedelta(days=30),
            "subscription_ends_at": now + timedelta(days=30),
            "approved_at": now - timedelta(days=30),
            "created_at": now,
            "updated_at": now,
            "gestor_limits_marker": MARKER,
        }
    )
    return str(seller_oid)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class GestorLimitsServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup()

    async def asyncTearDown(self) -> None:
        await cleanup()
        await close_mongo_connection()

    async def test_standard_plan_blocks_fourth_gestor(self) -> None:
        seller_id = await seed_seller(plan_tier="standard")

        for index in range(STANDARD_GESTOR_LIMIT):
            created = await gestor_service.create_seller_gestor(
                seller_id,
                f"gestor_std_{index}",
            )
            self.assertTrue(created.username.startswith("gestor_std_"))
            await get_gestores_collection().update_one(
                {"_id": ObjectId(created.id)},
                {"$set": {"gestor_limits_marker": MARKER}},
            )

        with self.assertRaises(Exception) as ctx:
            await gestor_service.create_seller_gestor(seller_id, "gestor_std_extra")

        exc = ctx.exception
        self.assertEqual(getattr(exc, "status_code", None), 403)
        self.assertIn("3", str(getattr(exc, "detail", exc)))
        self.assertIn("Premium", str(getattr(exc, "detail", exc)))

        count = await gestor_service.count_seller_gestores(seller_id)
        self.assertEqual(count, STANDARD_GESTOR_LIMIT)

    async def test_premium_plan_allows_more_than_three(self) -> None:
        seller_id = await seed_seller(plan_tier="premium")

        for index in range(STANDARD_GESTOR_LIMIT + 1):
            created = await gestor_service.create_seller_gestor(
                seller_id,
                f"gestor_prem_{index}",
            )
            await get_gestores_collection().update_one(
                {"_id": ObjectId(created.id)},
                {"$set": {"gestor_limits_marker": MARKER}},
            )

        count = await gestor_service.count_seller_gestores(seller_id)
        self.assertEqual(count, STANDARD_GESTOR_LIMIT + 1)


if __name__ == "__main__":
    unittest.main()
