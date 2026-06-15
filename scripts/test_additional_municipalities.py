"""
Tests unitarios del filtro geográfico con municipios_adicionales.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_additional_municipalities.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.marketplace import (
    _build_marketplace_products_query,
    _jaba_product_eligible,
    _marketplace_product_query,
    _normalize_additional_municipalities,
)
from app.services.product_popularity import MARKETPLACE_PRODUCT_SORT


class NormalizeAdditionalMunicipalitiesTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(
            _normalize_additional_municipalities("la-habana", "marianao", None),
            [],
        )
        self.assertEqual(
            _normalize_additional_municipalities("la-habana", "marianao", []),
            [],
        )

    def test_deduplicates_and_excludes_base_municipality(self) -> None:
        result = _normalize_additional_municipalities(
            "la-habana",
            "marianao",
            ["playa", "marianao", "playa", "centro-habana"],
        )
        self.assertEqual(result, ["playa", "centro-habana"])

    def test_rejects_invalid_municipality(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_additional_municipalities(
                "la-habana",
                "marianao",
                ["municipio-inexistente"],
            )


class MarketplaceProductQueryTests(unittest.TestCase):
    def test_without_pickup_sellers_preserves_existing_or_branches(self) -> None:
        query = _marketplace_product_query(
            local_seller_ids=["local-1"],
            delivery_seller_ids=["remote-1"],
        )
        self.assertEqual(query["is_available"], True)
        self.assertEqual(len(query["$or"]), 2)
        self.assertEqual(query["$or"][0], {"seller_id": {"$in": ["local-1"]}})
        self.assertEqual(
            query["$or"][1],
            {"seller_id": {"$in": ["remote-1"]}, "offers_delivery": True},
        )

    def test_with_pickup_sellers_adds_third_or_branch(self) -> None:
        query = _marketplace_product_query(
            local_seller_ids=["local-1"],
            delivery_seller_ids=["remote-1"],
            pickup_seller_ids=["pickup-1", "pickup-2"],
        )
        self.assertEqual(len(query["$or"]), 3)
        self.assertEqual(
            query["$or"][2],
            {"seller_id": {"$in": ["pickup-1", "pickup-2"]}},
        )

    def test_pickup_only_query_when_no_base_sellers(self) -> None:
        query = _marketplace_product_query(
            local_seller_ids=[],
            delivery_seller_ids=[],
            pickup_seller_ids=["pickup-1"],
        )
        self.assertEqual(len(query["$or"]), 1)
        self.assertEqual(query["$or"][0], {"seller_id": {"$in": ["pickup-1"]}})

    def test_build_query_keeps_category_and_search_filters(self) -> None:
        query = _build_marketplace_products_query(
            local_seller_ids=["local-1"],
            delivery_seller_ids=[],
            pickup_seller_ids=["pickup-1"],
            global_category_id="construccion-herramientas",
            search_text="martillo",
        )
        self.assertIn("$and", query)
        category_filter = query["$and"][0]["global_category_id"]
        self.assertEqual(set(category_filter["$in"]), {"construccion-herramientas", "construccion"})
        self.assertIn("$or", query["$and"][1])

    def test_recommendation_sort_unchanged(self) -> None:
        self.assertEqual(
            MARKETPLACE_PRODUCT_SORT,
            [("popularity", -1), ("sort_order", 1), ("name", 1)],
        )


class JabaProductEligibilityTests(unittest.TestCase):
    def _seller(self, seller_id: str, municipality_id: str) -> dict:
        return {
            "_id": seller_id,
            "status": "approved",
            "offers_delivery": True,
            "business_area": {
                "province_id": "la-habana",
                "municipality_id": municipality_id,
                "municipality_name": municipality_id,
            },
            "delivery_areas": [],
        }

    def test_rejects_remote_pickup_product_without_additional_municipality(self) -> None:
        seller = self._seller("remote-1", "playa")
        product = {"offers_delivery": False, "is_available": True, "view_only": False}
        reason = _jaba_product_eligible(
            product,
            seller,
            province_id="la-habana",
            municipality_id="marianao",
            visible_seller_ids={"remote-1"},
            pickup_seller_ids=set(),
        )
        self.assertEqual(reason, "no_delivery")

    def test_allows_remote_pickup_product_with_additional_municipality(self) -> None:
        seller = self._seller("remote-1", "playa")
        product = {"offers_delivery": False, "is_available": True, "view_only": False}
        reason = _jaba_product_eligible(
            product,
            seller,
            province_id="la-habana",
            municipality_id="marianao",
            visible_seller_ids={"remote-1"},
            pickup_seller_ids={"remote-1"},
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
