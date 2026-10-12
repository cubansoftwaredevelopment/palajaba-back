"""Recorrido de autocompletado: solo productos que ya están en pedidos."""

from __future__ import annotations

import unittest

from test_e2e.product_search.utils.fixtures import (
    cleanup_db,
    headers_for,
    seed_search_catalog,
)
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured

SEARCH_PATH = "/api/auth/me/catalog/products/search"


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ProductSearchE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()
        cls.seed = seed_search_catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def _search(self, seller_id: str, query: str = "") -> dict:
        params = {"q": query} if query else None
        with api_client() as client:
            response = client.get(
                SEARCH_PATH,
                params=params,
                headers=headers_for(seller_id),
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_blank_query_lists_only_ordered_available_products(self) -> None:
        body = self._search(self.seed["seller_id"])

        self.assertTrue(body["has_ordered_products"])
        self.assertEqual(body["total"], 2)
        self.assertEqual(
            [(item["name"], item["category_name"]) for item in body["products"]],
            [("Arroz Premium", "Despensa"), ("Café", "Bebidas")],
        )

    def test_name_search_is_case_insensitive_and_keeps_accents(self) -> None:
        upper = self._search(self.seed["seller_id"], "ARROZ")
        self.assertEqual(upper["total"], 1)
        self.assertEqual(upper["products"][0]["name"], "Arroz Premium")

        accent = self._search(self.seed["seller_id"], "CAFÉ")
        self.assertEqual([item["name"] for item in accent["products"]], ["Café"])

        without_accent = self._search(self.seed["seller_id"], "cafe")
        self.assertEqual(without_accent["total"], 0)
        self.assertEqual(without_accent["products"], [])
        self.assertTrue(without_accent["has_ordered_products"])

    def test_category_search_skips_products_that_were_never_ordered(self) -> None:
        body = self._search(self.seed["seller_id"], "despensa")

        self.assertEqual(body["total"], 1)
        self.assertEqual([item["name"] for item in body["products"]], ["Arroz Premium"])

        never_ordered = self._search(self.seed["seller_id"], "Jamón")
        self.assertEqual(never_ordered["total"], 0)
        self.assertEqual(never_ordered["products"], [])

    def test_hidden_ordered_products_stay_out_of_suggestions(self) -> None:
        view_only = self._search(self.seed["seller_id"], "aceite")
        unavailable = self._search(self.seed["seller_id"], "frijoles")

        self.assertEqual(view_only["total"], 0)
        self.assertEqual(unavailable["total"], 0)
        self.assertTrue(view_only["has_ordered_products"])

    def test_seller_without_orders_has_no_suggestions(self) -> None:
        body = self._search(self.seed["empty_seller_id"], "arroz")

        self.assertFalse(body["has_ordered_products"])
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["products"], [])


if __name__ == "__main__":
    unittest.main()
