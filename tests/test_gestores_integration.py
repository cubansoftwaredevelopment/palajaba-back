from __future__ import annotations

import os
import unittest
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from pymongo.errors import DuplicateKeyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_gestores_collection,
    get_registrations_collection,
)
from app.services import gestores as gestores_service

TEST_TRANSFER_PREFIX = "TEST-GESTOR-"
TEST_USERNAME_A = "test_gestor_alpha"
TEST_USERNAME_B = "test_gestor_beta"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


async def cleanup_gestor_test_data() -> None:
    await get_gestores_collection().delete_many(
        {"username": {"$in": [TEST_USERNAME_A, TEST_USERNAME_B]}}
    )
    await get_registrations_collection().delete_many(
        {"transfer_id": {"$regex": f"^{TEST_TRANSFER_PREFIX}"}}
    )


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class GestorIndexesIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_gestor_test_data()
        await gestores_service.ensure_gestor_indexes()
        await gestores_service.ensure_seller_gestor_catalog_defaults()

    async def asyncTearDown(self) -> None:
        await cleanup_gestor_test_data()
        await close_mongo_connection()

    async def test_username_unique_per_seller_not_global(self) -> None:
        seller_a = ObjectId()
        seller_b = ObjectId()

        doc_a = gestores_service.build_gestor_document(
            seller_id=seller_a,
            username=TEST_USERNAME_A,
        )
        created_a = await gestores_service.insert_gestor_document(doc_a)
        self.assertEqual(created_a["username"], TEST_USERNAME_A)
        self.assertIsNone(created_a["password_hash"])

        # Mismo username en otro negocio: OK
        doc_b = gestores_service.build_gestor_document(
            seller_id=seller_b,
            username=TEST_USERNAME_A,
        )
        created_b = await gestores_service.insert_gestor_document(doc_b)
        self.assertEqual(created_b["seller_id"], seller_b)

        # Mismo username en el mismo negocio: DuplicateKeyError
        with self.assertRaises(DuplicateKeyError):
            await gestores_service.insert_gestor_document(
                gestores_service.build_gestor_document(
                    seller_id=seller_a,
                    username=TEST_USERNAME_A,
                )
            )

    async def test_document_to_public_marks_pending_password(self) -> None:
        seller_id = ObjectId()
        created = await gestores_service.insert_gestor_document(
            gestores_service.build_gestor_document(
                seller_id=seller_id,
                username=TEST_USERNAME_B,
            )
        )
        public = gestores_service.document_to_gestor_public(created)
        self.assertEqual(public.username, TEST_USERNAME_B)
        self.assertFalse(public.has_password)
        self.assertIsNone(public.phone)
        self.assertEqual(public.selected_products, [])

    async def test_seller_gestor_catalog_access_backfill(self) -> None:
        collection = get_registrations_collection()
        seller_id = ObjectId()
        await collection.insert_one(
            {
                "_id": seller_id,
                "transfer_id": f"{TEST_TRANSFER_PREFIX}{seller_id}",
                "store_name": f"Tienda Test Gestor {seller_id}",
                "store_slug": f"tienda-test-gestor-{seller_id}",
                "phone": "59998877",
                "status": "approved",
            }
        )

        await gestores_service.ensure_seller_gestor_catalog_defaults()

        doc = await collection.find_one({"_id": seller_id})
        assert doc is not None
        access = gestores_service.parse_gestor_catalog_access(doc.get("gestor_catalog_access"))
        self.assertEqual(access.mode, "selected")
        self.assertEqual(access.product_ids, [])
        self.assertFalse(bool(doc.get("gestores_enabled")))


if __name__ == "__main__":
    unittest.main()
