"""Recorrido de categorías de negocio y de producto, de la API a Mongo."""

from __future__ import annotations

import unittest

from bson import ObjectId

from app.database import get_categories_collection, get_product_categories_collection, get_registrations_collection
from app.services.categories import DEFAULT_CATEGORIES
from app.services.product_categories import REVOLICO_PRODUCT_CATEGORIES
from test_e2e.utils.api import api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "categories_e2e_v1"


def _cleanup() -> None:
    async def work() -> None:
        await get_registrations_collection().delete_many({"categories_e2e_marker": MARKER})

    run_db(work)


def _seed_seller() -> dict[str, str]:
    seller_id = ObjectId()

    async def work() -> dict[str, str]:
        from datetime import timedelta

        from app.utils.datetime import to_utc_naive, utc_now

        now = to_utc_naive(utc_now())
        await get_registrations_collection().insert_one(
            {
                "_id": seller_id,
                "status": "approved",
                "store_name": f"TEST Categorias {seller_id}",
                "store_slug": f"test-categorias-{seller_id}",
                "transfer_id": f"TEST-CAT-{seller_id}",
                "phone": f"{int(str(seller_id), 16) % 100000000:08d}",
                "billing_period": "monthly",
                "plan_tier": "basic",
                "profile_photo_url": "https://example.com/photo.jpg",
                "category_ids": ["otros"],
                "offers_delivery": False,
                "business_area": {
                    "province_id": PROVINCE_ID,
                    "province_name": "La Habana",
                    "municipality_id": SELLER_MUNICIPALITY_ID,
                    "municipality_name": "Playa",
                },
                "subscription_starts_at": now - timedelta(days=1),
                "subscription_ends_at": now + timedelta(days=20),
                "categories_e2e_marker": MARKER,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {"seller_id": str(seller_id), "store_name": f"TEST Categorias {seller_id}"}

    return run_db(work)


def _category_docs() -> tuple[dict[str, str], list[str]]:
    async def work() -> tuple[dict[str, str], list[str]]:
        business = {
            doc["id"]: doc["name"]
            async for doc in get_categories_collection().find({}, projection={"id": 1, "name": 1})
        }
        products = [
            doc["id"]
            async for doc in get_product_categories_collection().find({}, projection={"id": 1}).sort("sort_order", 1)
        ]
        return business, products

    return run_db(work)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CategoriesE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup()
        cls.seller = _seed_seller()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup()

    def test_business_categories_match_the_catalog_and_stay_in_mongo(self) -> None:
        with api_client() as client:
            response = client.get("/api/categories/")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        expected = sorted(DEFAULT_CATEGORIES, key=lambda item: item["name"].lower())
        self.assertEqual([(item["id"], item["name"]) for item in body], [(item["id"], item["name"]) for item in expected])
        self.assertEqual(len(body), len({item["id"] for item in body}))

        stored, _products = _category_docs()
        for category in DEFAULT_CATEGORIES:
            self.assertEqual(stored.get(category["id"]), category["name"])

    def test_product_categories_follow_the_catalog_order(self) -> None:
        with api_client() as client:
            response = client.get("/api/product-categories/")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        expected = sorted(REVOLICO_PRODUCT_CATEGORIES, key=lambda item: item["sort_order"])
        self.assertEqual(
            [(item["id"], item["name"]) for item in body],
            [(item["id"], item["name"]) for item in expected],
        )
        self.assertEqual(body[0]["id"], "electrodomesticos")
        self.assertEqual(body[-1]["id"], "otros")

        _business, stored_ids = _category_docs()
        self.assertEqual(stored_ids, [item["id"] for item in expected])

    def test_seller_can_save_a_category_alias_and_read_it_back(self) -> None:
        payload = {
            "business_area": {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": SELLER_MUNICIPALITY_ID,
                "municipality_name": "Playa",
            },
            "offers_delivery": False,
            "category_ids": ["vehiculos-repuestos", "comida"],
        }
        headers = seller_auth_headers(
            seller_id=self.seller["seller_id"],
            store_name=self.seller["store_name"],
        )

        with api_client() as client:
            saved = client.patch("/api/auth/me/profile", json=payload, headers=headers)
            listed = client.get("/api/auth/me/business-categories", headers=headers)

        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["category_ids"], ["vehiculos-repuestos", "comida"])
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(
            listed.json(),
            [
                {"id": "vehiculos-repuestos", "name": "Medios de transporte"},
                {"id": "comida", "name": "Comida y bebidas"},
            ],
        )
