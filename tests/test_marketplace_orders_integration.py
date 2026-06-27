from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from dotenv import load_dotenv
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_orders_collection,
    get_registrations_collection,
)
from app.main import app
from tests.helpers_marketplace_orders import MARKER, order_payload, seller_document


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


async def cleanup_marketplace_orders_test_data() -> None:
    await get_orders_collection().delete_many({"store_name": seller_document()["store_name"]})
    await get_registrations_collection().delete_many({"marketplace_orders_test_marker": MARKER})


async def seed_marketplace_orders_seller() -> str:
    seller_oid = ObjectId()
    await get_registrations_collection().insert_one(seller_document(seller_id=seller_oid))
    return str(seller_oid)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class MarketplaceOrdersIntegrationTests(unittest.TestCase):
    seller_id: str

    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> str:
            await connect_to_mongo()
            await cleanup_marketplace_orders_test_data()
            return await seed_marketplace_orders_seller()

        cls.seller_id = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_marketplace_orders_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    @patch(
        "app.services.orders.notification_service.notify_seller_new_order",
        new_callable=AsyncMock,
    )
    def test_create_marketplace_order_persists_pending_confirmation(self, mock_notify) -> None:
        with TestClient(app) as client:
            calls_before = mock_notify.await_count
            payload = order_payload(store_id=self.seller_id)
            response = client.post("/api/marketplace/orders", json=payload)

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["store_id"], self.seller_id)
        self.assertEqual(body["status"], "pending_confirmation")
        self.assertFalse(body["delivery_requested"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["quantity"], 2)
        self.assertEqual(mock_notify.await_count, calls_before + 1)

    @patch(
        "app.services.orders.notification_service.notify_seller_new_order",
        new_callable=AsyncMock,
    )
    def test_create_marketplace_order_with_delivery(self, mock_notify) -> None:
        with TestClient(app) as client:
            calls_before = mock_notify.await_count
            payload = order_payload(store_id=self.seller_id, with_delivery=True)
            response = client.post("/api/marketplace/orders", json=payload)

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["delivery_requested"])
        self.assertEqual(body["delivery"]["recipient_name"], "María López")
        self.assertEqual(mock_notify.await_count, calls_before + 1)

    def test_create_marketplace_order_rejects_invalid_store(self) -> None:
        with TestClient(app) as client:
            payload = order_payload(store_id=str(ObjectId()))
            response = client.post("/api/marketplace/orders", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("no encontrada", response.json()["detail"].lower())

    def test_create_marketplace_order_rejects_empty_items(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/marketplace/orders",
                json={"store_id": self.seller_id, "items": []},
            )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
