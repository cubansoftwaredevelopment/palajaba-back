from __future__ import annotations

import os
import unittest
from datetime import timedelta
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_registrations_collection,
)
from app.main import app
from app.security import create_seller_token
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "seller_store_name_test_v1"
STORE_NAME = "TEST Seller Store Name"
STORE_SLUG = "test-seller-store-name"
OTHER_STORE_NAME = "TEST Seller Store Name Other"
OTHER_STORE_SLUG = "test-seller-store-name-other"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(
    *,
    seller_id: ObjectId,
    store_name: str,
    store_slug: str,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name,
        "store_slug": store_slug,
        "transfer_id": f"TEST-STORE-NAME-{seller_id}",
        "phone": _unique_phone(seller_id),
        "password_hash": "test",
        "billing_period": "monthly",
        "plan_tier": "standard",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "delivery_areas": [],
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "seller_store_name_test_marker": MARKER,
    }


class SellerStoreNameSeed:
    seller_id: str
    other_seller_id: str


async def cleanup_seller_store_name_test_data() -> None:
    registrations = get_registrations_collection()
    await registrations.delete_many({"seller_store_name_test_marker": MARKER})


async def seed_seller_store_name_test_data() -> SellerStoreNameSeed:
    seed = SellerStoreNameSeed()
    seller_oid = ObjectId()
    other_seller_oid = ObjectId()
    seed.seller_id = str(seller_oid)
    seed.other_seller_id = str(other_seller_oid)

    registrations = get_registrations_collection()
    await registrations.insert_one(
        seller_document(
            seller_id=seller_oid,
            store_name=STORE_NAME,
            store_slug=STORE_SLUG,
        )
    )
    await registrations.insert_one(
        seller_document(
            seller_id=other_seller_oid,
            store_name=OTHER_STORE_NAME,
            store_slug=OTHER_STORE_SLUG,
        )
    )
    return seed


def seller_auth_header(seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SellerStoreNameApiIntegrationTests(unittest.TestCase):
    seed: SellerStoreNameSeed

    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        async def prepare() -> SellerStoreNameSeed:
            await connect_to_mongo()
            await cleanup_seller_store_name_test_data()
            return await seed_seller_store_name_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_seller_store_name_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_patch_store_name_persists_new_name_and_slug(self) -> None:
        new_name = "TEST Seller Store Renamed"
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/store-name",
                headers=seller_auth_header(self.seed.seller_id, STORE_NAME),
                json={"store_name": new_name},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["store_name"], new_name)

        import asyncio

        async def verify_db() -> None:
            await connect_to_mongo()
            doc = await get_registrations_collection().find_one(
                {"_id": ObjectId(self.seed.seller_id)}
            )
            await close_mongo_connection()
            self.assertEqual(doc["store_name"], new_name)
            self.assertEqual(doc["store_slug"], store_name_to_slug(new_name))

        asyncio.run(verify_db())

    def test_patch_store_name_rejects_duplicate(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/store-name",
                headers=seller_auth_header(self.seed.seller_id, STORE_NAME),
                json={"store_name": OTHER_STORE_NAME},
            )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("ya está ocupado", response.json()["detail"])

    def test_patch_store_name_rejects_duplicate_case_insensitive(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/store-name",
                headers=seller_auth_header(self.seed.seller_id, STORE_NAME),
                json={"store_name": OTHER_STORE_NAME.lower()},
            )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("ya está ocupado", response.json()["detail"])

    def test_patch_store_name_noop_when_same_name(self) -> None:
        import asyncio

        async def reset_name() -> None:
            await connect_to_mongo()
            await get_registrations_collection().update_one(
                {"_id": ObjectId(self.seed.seller_id)},
                {
                    "$set": {
                        "store_name": STORE_NAME,
                        "store_slug": STORE_SLUG,
                    }
                },
            )
            await close_mongo_connection()

        asyncio.run(reset_name())

        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/store-name",
                headers=seller_auth_header(self.seed.seller_id, STORE_NAME),
                json={"store_name": STORE_NAME},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["store_name"], STORE_NAME)


if __name__ == "__main__":
    unittest.main(verbosity=2)
