from __future__ import annotations

import asyncio
import os
import unittest
from datetime import timedelta
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (  # noqa: E402
    close_mongo_connection,
    connect_to_mongo,
    get_notifications_collection,
    get_registrations_collection,
)
from app.main import app  # noqa: E402
from app.security import create_admin_token  # noqa: E402
from app.services import notifications as notification_service  # noqa: E402
from app.utils.datetime import to_utc_naive, utc_now  # noqa: E402
from tests.helpers_seller_stats import seller_document  # noqa: E402

MARKER = "admin_notifications_single_test_v1"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def admin_auth_header() -> dict[str, str]:
    token = create_admin_token(username="notif-admin", admin_id=str(ObjectId()))
    return {"Authorization": f"Bearer {token}"}


async def cleanup() -> None:
    await get_notifications_collection().delete_many({"admin_notifications_marker": MARKER})
    await get_registrations_collection().delete_many({"admin_notifications_marker": MARKER})


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminSingleNotificationServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup()
        self.seller_id = ObjectId()
        seller = seller_document(seller_id=self.seller_id, store_name="Tienda Notif Target")
        seller["admin_notifications_marker"] = MARKER
        seller["subscription_ends_at"] = to_utc_naive(utc_now()) + timedelta(days=20)
        await get_registrations_collection().insert_one(seller)
        self.admin_id = str(ObjectId())

    async def asyncTearDown(self) -> None:
        await cleanup()
        await close_mongo_connection()

    async def test_send_to_single_seller(self) -> None:
        result = await notification_service.send_notification_to_sellers(
            self.admin_id,
            "Aviso puntual",
            "Hola, este mensaje es solo para ti.",
            "all",
            seller_id=str(self.seller_id),
        )
        self.assertEqual(result.audience, "single")
        self.assertEqual(result.recipient_count, 1)
        self.assertEqual(result.target_store_name, "Tienda Notif Target")

        docs = await get_notifications_collection().find(
            {"batch_id": result.batch_id},
        ).to_list(length=None)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["seller_id"], self.seller_id)
        self.assertEqual(docs[0]["audience"], "single")

        await get_notifications_collection().update_many(
            {"batch_id": result.batch_id},
            {"$set": {"admin_notifications_marker": MARKER}},
        )

        history = await notification_service.list_admin_broadcasts(limit=30)
        match = next((item for item in history if item.batch_id == result.batch_id), None)
        self.assertIsNotNone(match)
        self.assertEqual(match.target_store_name, "Tienda Notif Target")

    async def test_send_to_missing_seller_fails(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await notification_service.send_notification_to_sellers(
                self.admin_id,
                "Aviso",
                "Mensaje",
                seller_id=str(ObjectId()),
            )
        self.assertEqual(ctx.exception.status_code, 404)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminSingleNotificationApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> ObjectId:
            await connect_to_mongo()
            await cleanup()
            seller_id = ObjectId()
            seller = seller_document(seller_id=seller_id, store_name="API Notif Store")
            seller["admin_notifications_marker"] = MARKER
            seller["subscription_ends_at"] = to_utc_naive(utc_now()) + timedelta(days=10)
            await get_registrations_collection().insert_one(seller)
            await close_mongo_connection()
            return seller_id

        cls.seller_id = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_post_single_notification(self) -> None:
        headers = admin_auth_header()
        with TestClient(app) as client:
            response = client.post(
                "/api/admin/notifications",
                headers=headers,
                json={
                    "title": "Aviso API",
                    "content": "Solo para esta tienda",
                    "seller_id": str(self.seller_id),
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["audience"], "single")
            self.assertEqual(body["recipient_count"], 1)
            self.assertEqual(body["target_store_name"], "API Notif Store")

        async def mark() -> None:
            await connect_to_mongo()
            await get_notifications_collection().update_many(
                {"batch_id": body["batch_id"]},
                {"$set": {"admin_notifications_marker": MARKER}},
            )
            await close_mongo_connection()

        asyncio.run(mark())


if __name__ == "__main__":
    unittest.main()
