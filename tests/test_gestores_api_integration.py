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

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_products_collection,
    get_gestores_collection,
    get_registrations_collection,
)
from app.main import app
from app.security import create_seller_token
from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "gestores_api_test_v1"
STORE_NAME = "TEST Gestores API Store"
STORE_SLUG = "test-gestores-api-store"
GESTOR_USER = "gestor_api_pepe"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def seller_auth_header(seller_id: str, store_name: str = STORE_NAME) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_seller_token(seller_id=seller_id, store_name=store_name)}"
    }


class GestoresApiSeed:
    seller_id: str
    product_allowed_id: str
    product_other_id: str


async def cleanup_gestores_api_test_data(seller_id: str | None = None) -> None:
    if seller_id:
        await get_gestores_collection().delete_many(
            {"seller_id": {"$in": [ObjectId(seller_id), seller_id]}}
        )
    await get_gestores_collection().delete_many({"username": GESTOR_USER})
    await get_catalog_products_collection().delete_many({"gestores_api_test_marker": MARKER})
    await get_registrations_collection().delete_many({"gestores_api_test_marker": MARKER})


async def seed_gestores_api_test_data() -> GestoresApiSeed:
    seed = GestoresApiSeed()
    seller_oid = ObjectId()
    seed.seller_id = str(seller_oid)
    now = to_utc_naive(utc_now())

    await get_registrations_collection().insert_one(
        {
            "_id": seller_oid,
            "status": "approved",
            "store_name": STORE_NAME,
            "store_slug": STORE_SLUG,
            "transfer_id": f"TEST-GESTOR-API-{seller_oid}",
            "phone": f"{int(str(seller_oid), 16) % 100000000:08d}",
            "billing_period": "monthly",
            "plan_tier": "premium",
            "profile_photo_url": "https://example.com/photo.jpg",
            "category_ids": ["food"],
            "offers_delivery": True,
            "business_area": {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": SELLER_MUNICIPALITY_ID,
                "municipality_name": "Playa",
            },
            "gestor_catalog_access": {"mode": "selected", "product_ids": []},
            "gestores_enabled": True,
            "subscription_starts_at": now - timedelta(days=30),
            "subscription_ends_at": now + timedelta(days=30),
            "approved_at": now - timedelta(days=30),
            "created_at": now,
            "updated_at": now,
            "gestores_api_test_marker": MARKER,
        }
    )

    category_id = ObjectId()
    product_a = {
        "seller_id": seed.seller_id,
        "category_id": category_id,
        "global_category_id": "otros",
        "name": "Producto permitido",
        "description": "Demo",
        "image_url": "https://example.com/a.jpg",
        "base_price": 2500.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": True,
        "is_available": True,
        "view_only": False,
        "popularity": 0,
        "sort_order": 0,
        "created_at": now,
        "updated_at": now,
        "gestores_api_test_marker": MARKER,
    }
    product_b = {
        **product_a,
        "name": "Producto no permitido",
        "base_price": 1000.0,
        "image_url": "https://example.com/b.jpg",
    }
    result_a = await get_catalog_products_collection().insert_one(product_a)
    result_b = await get_catalog_products_collection().insert_one(product_b)
    seed.product_allowed_id = str(result_a.inserted_id)
    seed.product_other_id = str(result_b.inserted_id)
    return seed


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class GestoresApiIntegrationTests(unittest.TestCase):
    seed: GestoresApiSeed

    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> GestoresApiSeed:
            await connect_to_mongo()
            await cleanup_gestores_api_test_data()
            return await seed_gestores_api_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_gestores_api_test_data(cls.seed.seller_id)
            await close_mongo_connection()

        asyncio.run(finalize())

    def setUp(self) -> None:
        async def reset() -> None:
            await connect_to_mongo()
            await get_gestores_collection().delete_many(
                {"seller_id": {"$in": [ObjectId(self.seed.seller_id), self.seed.seller_id]}}
            )
            await get_registrations_collection().update_one(
                {"_id": ObjectId(self.seed.seller_id)},
                {
                    "$set": {
                        "gestor_catalog_access": {"mode": "selected", "product_ids": []},
                        "gestores_enabled": True,
                    }
                },
            )

        asyncio.run(reset())

    def test_seller_create_list_delete_gestor(self) -> None:
        headers = seller_auth_header(self.seed.seller_id)
        with TestClient(app) as client:
            create = client.post(
                "/api/auth/me/gestores",
                headers=headers,
                json={"username": GESTOR_USER},
            )
            self.assertEqual(create.status_code, 201, create.text)
            body = create.json()
            self.assertEqual(body["username"], GESTOR_USER)
            self.assertFalse(body["has_password"])
            gestor_id = body["id"]

            listed = client.get("/api/auth/me/gestores", headers=headers)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()), 1)

            conflict = client.post(
                "/api/auth/me/gestores",
                headers=headers,
                json={"username": GESTOR_USER},
            )
            self.assertEqual(conflict.status_code, 409)

            deleted = client.delete(f"/api/auth/me/gestores/{gestor_id}", headers=headers)
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json()["id"], gestor_id)

    def test_seller_catalog_access_and_gestor_product_selection_flow(self) -> None:
        headers = seller_auth_header(self.seed.seller_id)

        with TestClient(app) as client:
            created = client.post(
                "/api/auth/me/gestores",
                headers=headers,
                json={"username": GESTOR_USER},
            )
            self.assertEqual(created.status_code, 201, created.text)

            access = client.put(
                "/api/auth/me/gestores/catalog-access",
                headers=headers,
                json={
                    "mode": "selected",
                    "product_ids": [self.seed.product_allowed_id],
                },
            )
            self.assertEqual(access.status_code, 200, access.text)
            self.assertEqual(access.json()["mode"], "selected")
            self.assertEqual(access.json()["product_ids"], [self.seed.product_allowed_id])

            login = client.post(
                "/api/gestores/login",
                json={"store_name": STORE_NAME, "username": GESTOR_USER},
            )
            self.assertEqual(login.status_code, 200, login.text)
            login_body = login.json()
            self.assertIsNotNone(login_body["requires_setup"])
            setup_token = login_body["requires_setup"]["setup_token"]

            setup = client.post(
                "/api/gestores/setup",
                json={
                    "setup_token": setup_token,
                    "password": "clave123",
                    "phone": "51234567",
                },
            )
            self.assertEqual(setup.status_code, 200, setup.text)
            setup_body = setup.json()
            self.assertTrue(setup_body["access_token"])
            self.assertTrue(setup_body["gestor"]["has_password"])
            gestor_headers = {"Authorization": f"Bearer {setup_body['access_token']}"}

            allowed = client.get("/api/gestores/me/allowed-products", headers=gestor_headers)
            self.assertEqual(allowed.status_code, 200, allowed.text)
            allowed_ids = {item["product_id"] for item in allowed.json()}
            self.assertIn(self.seed.product_allowed_id, allowed_ids)
            self.assertNotIn(self.seed.product_other_id, allowed_ids)

            selected = client.put(
                "/api/gestores/me/selected-products",
                headers=gestor_headers,
                json={
                    "products": [
                        {"product_id": self.seed.product_allowed_id, "margin_amount": 300},
                    ]
                },
            )
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertEqual(len(selected.json()["selected_products"]), 1)
            self.assertEqual(selected.json()["selected_products"][0]["margin_amount"], 300)

            bad = client.put(
                "/api/gestores/me/selected-products",
                headers=gestor_headers,
                json={
                    "products": [
                        {"product_id": self.seed.product_other_id, "margin_amount": 50},
                    ]
                },
            )
            self.assertEqual(bad.status_code, 400)

            login2 = client.post(
                "/api/gestores/login",
                json={
                    "store_name": STORE_NAME,
                    "username": GESTOR_USER,
                    "password": "clave123",
                },
            )
            self.assertEqual(login2.status_code, 200, login2.text)
            self.assertTrue(login2.json()["access_token"])
            self.assertIsNone(login2.json()["requires_setup"])

            wrong = client.post(
                "/api/gestores/login",
                json={
                    "store_name": STORE_NAME,
                    "username": GESTOR_USER,
                    "password": "mala",
                },
            )
            self.assertEqual(wrong.status_code, 401)


if __name__ == "__main__":
    unittest.main()
