"""Recorrido de categorías de negocio y de producto, de la API a Mongo."""

from __future__ import annotations

import unittest

from app.services.categories import DEFAULT_CATEGORIES
from app.catalogs.catalog_theme import REVOLICO_PRODUCT_CATEGORIES
from test_e2e.categories.utils.fixtures import cleanup_db, load_category_documents, seed_seller
from test_e2e.utils.api import api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CategoriesE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()
        cls.seller = seed_seller()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_business_categories_match_the_catalog_and_stay_in_mongo(self) -> None:
        with api_client() as client:
            response = client.get("/api/categories/")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        expected = sorted(DEFAULT_CATEGORIES, key=lambda item: item["name"].lower())
        self.assertEqual([(item["id"], item["name"]) for item in body], [(item["id"], item["name"]) for item in expected])
        self.assertEqual(len(body), len({item["id"] for item in body}))

        stored, _products = load_category_documents()
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

        _business, stored_ids = load_category_documents()
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
        expected = sorted(DEFAULT_CATEGORIES, key=lambda item: item["name"].lower())
        self.assertEqual(
            [(item["id"], item["name"]) for item in listed.json()],
            [(item["id"], item["name"]) for item in expected],
        )
