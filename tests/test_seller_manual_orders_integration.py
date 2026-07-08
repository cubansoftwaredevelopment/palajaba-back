from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.main import app
from app.security import create_seller_token
from tests.helpers_manual_orders import (
    MARKER,
    STORE_NAME_A,
    STORE_NAME_B,
    category_document,
    manual_order_payload,
    product_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def seller_auth_header(seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}


class ManualOrdersSeed:
    seller_a_id: str
    seller_b_id: str
    product_a_id: str
    product_b_id: str
    low_stock_product_id: str


async def cleanup_manual_orders_test_data() -> None:
    orders = get_orders_collection()
    products = get_catalog_products_collection()
    registrations = get_registrations_collection()
    await orders.delete_many({"store_name": {"$in": [STORE_NAME_A, STORE_NAME_B]}})
    await products.delete_many({"seller_manual_orders_test_marker": MARKER})
    await registrations.delete_many({"seller_manual_orders_test_marker": MARKER})


async def seed_manual_orders_test_data() -> ManualOrdersSeed:
    seed = ManualOrdersSeed()
    seller_a_oid = ObjectId()
    seller_b_oid = ObjectId()
    seed.seller_a_id = str(seller_a_oid)
    seed.seller_b_id = str(seller_b_oid)

    registrations = get_registrations_collection()
    products = get_catalog_products_collection()

    await registrations.insert_one(seller_document(seller_id=seller_a_oid, store_name=STORE_NAME_A))
    await registrations.insert_one(
        seller_document(seller_id=seller_b_oid, store_name=STORE_NAME_B),
    )

    category_a = category_document(seller_id=seed.seller_a_id)
    category_b = category_document(seller_id=seed.seller_b_id)

    product_a = product_document(
        seller_id=seed.seller_a_id,
        category_id=category_a["_id"],
        name="Producto con stock",
        stock_quantity=5,
    )
    product_low_stock = product_document(
        seller_id=seed.seller_a_id,
        category_id=category_a["_id"],
        name="Producto casi agotado",
        stock_quantity=1,
    )
    product_b = product_document(
        seller_id=seed.seller_b_id,
        category_id=category_b["_id"],
        name="Producto ajeno",
        stock_quantity=3,
    )

    result_a = await products.insert_one(product_a)
    result_low = await products.insert_one(product_low_stock)
    result_b = await products.insert_one(product_b)

    seed.product_a_id = str(result_a.inserted_id)
    seed.low_stock_product_id = str(result_low.inserted_id)
    seed.product_b_id = str(result_b.inserted_id)
    return seed


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SellerManualOrdersIntegrationTests(unittest.TestCase):
    seed: ManualOrdersSeed

    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> ManualOrdersSeed:
            await connect_to_mongo()
            await cleanup_manual_orders_test_data()
            return await seed_manual_orders_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_manual_orders_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_create_manual_order_persists_structure_and_decrements_stock(self) -> None:
        payload = manual_order_payload(product_id=self.seed.product_a_id, quantity=2)
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/me/orders",
                json=payload,
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["origin"], "manual")
        self.assertEqual(body["status"], "pending_confirmation")
        self.assertEqual(body["items"][0]["product_id"], self.seed.product_a_id)
        self.assertEqual(body["items"][0]["quantity"], 2)
        self.assertEqual(body["payment_currency"], "CUP")
        self.assertFalse(body["delivery_requested"])

        async def read_stock() -> int:
            await connect_to_mongo()
            doc = await get_catalog_products_collection().find_one(
                {"_id": ObjectId(self.seed.product_a_id)},
            )
            return int(doc["stock_quantity"])

        self.assertEqual(asyncio.run(read_stock()), 3)

    def test_create_manual_order_rejects_insufficient_stock(self) -> None:
        payload = manual_order_payload(product_id=self.seed.low_stock_product_id, quantity=2)
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/me/orders",
                json=payload,
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("stock insuficiente", response.json()["detail"].lower())

        async def read_stock() -> int:
            await connect_to_mongo()
            doc = await get_catalog_products_collection().find_one(
                {"_id": ObjectId(self.seed.low_stock_product_id)},
            )
            return int(doc["stock_quantity"])

        self.assertEqual(asyncio.run(read_stock()), 1)

    def test_seller_cannot_register_other_seller_products(self) -> None:
        payload = manual_order_payload(product_id=self.seed.product_b_id, quantity=1)
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/me/orders",
                json=payload,
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("otra tienda", response.json()["detail"].lower())
