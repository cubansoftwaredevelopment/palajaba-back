from __future__ import annotations

import os
import unittest

from starlette.testclient import TestClient

from app.main import app
from app.services.categories import DEFAULT_CATEGORIES


class BusinessCategoriesApiTests(unittest.TestCase):
    def test_list_categories_includes_new_globals(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/categories/")
        self.assertEqual(response.status_code, 200, response.text)
        by_id = {item["id"]: item for item in response.json()}
        self.assertEqual(by_id["articulos-limpieza"]["name"], "Articulos de limpieza")
        self.assertEqual(
            by_id["suplementos-gimnasio"]["name"],
            "Suplementos y articulos de gimnasio",
        )

    def test_default_categories_have_unique_ids(self) -> None:
        ids = [item["id"] for item in DEFAULT_CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))


@unittest.skipUnless(os.getenv("MONGODB_URL", "").strip(), "MONGODB_URL no configurada")
class BusinessCategoriesSeedIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from app.database import connect_to_mongo

        await connect_to_mongo()

    async def asyncTearDown(self) -> None:
        from app.database import close_mongo_connection

        await close_mongo_connection()

    async def test_seed_upserts_new_categories_in_mongo(self) -> None:
        from app.database import get_categories_collection
        from app.services.categories import ensure_category_seed

        await ensure_category_seed()
        collection = get_categories_collection()
        for category_id, expected_name in (
            ("articulos-limpieza", "Articulos de limpieza"),
            ("suplementos-gimnasio", "Suplementos y articulos de gimnasio"),
        ):
            doc = await collection.find_one({"id": category_id})
            self.assertIsNotNone(doc, f"falta {category_id} en MongoDB")
            self.assertEqual(doc.get("name"), expected_name)
