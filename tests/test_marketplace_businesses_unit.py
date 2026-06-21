from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from tests.helpers import PROVINCE_ID, REMOTE_MUNICIPALITY_ID, SELLER_MUNICIPALITY_ID, seller_document
from app.services import marketplace as marketplace_service
from app.services.marketplace import (
    _business_pickup_info,
    _business_to_public,
    _seller_matches_business_category,
    _seller_matches_business_search,
    list_businesses,
)


def _seller_with_name(
    name: str,
    *,
    seller_id: str,
    municipality_id: str = SELLER_MUNICIPALITY_ID,
    category_ids: list[str] | None = None,
    offers_delivery: bool = True,
    biography: str | None = None,
) -> dict:
    doc = seller_document()
    doc["_id"] = seller_id
    doc["store_name"] = name
    doc["store_slug"] = name.lower().replace(" ", "-")
    doc["offers_delivery"] = offers_delivery
    doc["category_ids"] = category_ids or ["food"]
    if biography is not None:
        doc["biography"] = biography
    doc["business_area"] = {
        "province_id": PROVINCE_ID,
        "province_name": "La Habana",
        "municipality_id": municipality_id,
        "municipality_name": "Playa" if municipality_id == SELLER_MUNICIPALITY_ID else "Marianao",
    }
    if municipality_id == REMOTE_MUNICIPALITY_ID and offers_delivery:
        doc["delivery_areas"] = [
            {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": SELLER_MUNICIPALITY_ID,
                "municipality_name": "Playa",
            }
        ]
    else:
        doc["delivery_areas"] = []
    return doc


class BusinessPickupTests(unittest.TestCase):
    def test_local_seller_has_no_pickup_notice(self) -> None:
        seller = _seller_with_name("Local", seller_id="local-1")
        required, municipality, notice = _business_pickup_info(
            seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertFalse(required)
        self.assertIsNone(municipality)
        self.assertIsNone(notice)

    def test_remote_delivery_seller_has_no_pickup_notice(self) -> None:
        seller = _seller_with_name(
            "Delivery",
            seller_id="delivery-1",
            municipality_id=REMOTE_MUNICIPALITY_ID,
            offers_delivery=True,
        )
        required, municipality, notice = _business_pickup_info(
            seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertFalse(required)
        self.assertIsNone(municipality)
        self.assertIsNone(notice)

    def test_remote_pickup_only_seller_shows_notice(self) -> None:
        seller = _seller_with_name(
            "Pickup only",
            seller_id="pickup-1",
            municipality_id=REMOTE_MUNICIPALITY_ID,
            offers_delivery=False,
        )
        required, municipality, notice = _business_pickup_info(
            seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertTrue(required)
        self.assertEqual(municipality, "Marianao")
        self.assertEqual(notice, "Sin domicilio a tu municipio · Recoger en Marianao")


class BusinessFilterTests(unittest.TestCase):
    def test_search_matches_store_name_and_biography(self) -> None:
        seller = _seller_with_name("Panadería Central", seller_id="s1", biography="Especialistas en pan")
        self.assertTrue(_seller_matches_business_search(seller, "panadería"))
        self.assertTrue(_seller_matches_business_search(seller, "pan"))
        self.assertFalse(_seller_matches_business_search(seller, "zapatería"))

    def test_category_filter_matches_business_category(self) -> None:
        seller = _seller_with_name("Comida", seller_id="s1", category_ids=["food"])
        self.assertTrue(_seller_matches_business_category(seller, "food"))
        self.assertFalse(_seller_matches_business_category(seller, "construccion"))


class BusinessToPublicTests(unittest.TestCase):
    def test_maps_store_categories_pickup_and_flags(self) -> None:
        seller = _seller_with_name(
            "Pickup only",
            seller_id="pickup-1",
            municipality_id=REMOTE_MUNICIPALITY_ID,
            offers_delivery=False,
        )
        seller_id = str(seller["_id"])

        business = _business_to_public(
            seller,
            popularity=12,
            is_local=False,
            published_product_count=7,
            province_id=PROVINCE_ID,
            municipality_id=SELLER_MUNICIPALITY_ID,
        )

        self.assertEqual(business.store.id, seller_id)
        self.assertEqual(business.popularity, 12)
        self.assertFalse(business.is_local)
        self.assertEqual(business.published_product_count, 7)
        self.assertTrue(business.pickup_required)
        self.assertEqual(business.pickup_municipality_name, "Marianao")
        self.assertIn("Recoger en Marianao", business.pickup_notice or "")


class ListBusinessesTests(unittest.IsolatedAsyncioTestCase):
    def _mock_context(self, sellers: dict[str, dict]) -> tuple[dict, list, list, list]:
        local_ids = [
            seller_id
            for seller_id, seller in sellers.items()
            if seller["business_area"]["municipality_id"] == SELLER_MUNICIPALITY_ID
        ]
        delivery_ids = [
            seller_id
            for seller_id, seller in sellers.items()
            if seller_id not in local_ids
        ]
        return sellers, local_ids, delivery_ids, []

    @patch.object(marketplace_service, "aggregate_product_counts_by_seller", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_aggregate_seller_popularity", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_build_marketplace_seller_context", new_callable=AsyncMock)
    async def test_sorts_by_popularity_then_name(self, mock_context, mock_popularity, mock_counts) -> None:
        seller_a = _seller_with_name("Alfa Tienda", seller_id="seller-a")
        seller_b = _seller_with_name("Bravo Tienda", seller_id="seller-b")
        seller_c = _seller_with_name(
            "Charlie Tienda",
            seller_id="seller-c",
            municipality_id=REMOTE_MUNICIPALITY_ID,
        )
        sellers = {
            "seller-a": seller_a,
            "seller-b": seller_b,
            "seller-c": seller_c,
        }
        mock_context.return_value = self._mock_context(sellers)
        mock_popularity.return_value = {
            "seller-a": 5,
            "seller-b": 10,
            "seller-c": 10,
        }
        mock_counts.return_value = {
            "seller-a": {"published": 2},
            "seller-b": {"published": 4},
            "seller-c": {"published": 1},
        }

        result = await list_businesses(
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            limit=20,
            offset=0,
        )

        names = [item.store.store_name for item in result.businesses]
        self.assertEqual(names, ["Bravo Tienda", "Charlie Tienda", "Alfa Tienda"])
        self.assertEqual(result.total_businesses, 3)
        self.assertFalse(result.has_more)
        self.assertEqual(result.businesses[0].published_product_count, 4)
        self.assertFalse(result.businesses[1].pickup_required)

    @patch.object(marketplace_service, "aggregate_product_counts_by_seller", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_aggregate_seller_popularity", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_build_marketplace_seller_context", new_callable=AsyncMock)
    async def test_filters_by_query_and_category(self, mock_context, mock_popularity, mock_counts) -> None:
        sellers = {
            "seller-a": _seller_with_name("Panadería Alfa", seller_id="seller-a", category_ids=["food"]),
            "seller-b": _seller_with_name("Ferretería Beta", seller_id="seller-b", category_ids=["construccion"]),
        }
        mock_context.return_value = self._mock_context(sellers)
        mock_popularity.return_value = {"seller-a": 1, "seller-b": 2}
        mock_counts.return_value = {
            "seller-a": {"published": 1},
            "seller-b": {"published": 1},
        }

        by_query = await list_businesses(
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            query="panader",
            limit=20,
            offset=0,
        )
        self.assertEqual([item.store.store_name for item in by_query.businesses], ["Panadería Alfa"])

        by_category = await list_businesses(
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            category_id="construccion",
            limit=20,
            offset=0,
        )
        self.assertEqual([item.store.store_name for item in by_category.businesses], ["Ferretería Beta"])

    @patch.object(marketplace_service, "aggregate_product_counts_by_seller", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_aggregate_seller_popularity", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_build_marketplace_seller_context", new_callable=AsyncMock)
    async def test_paginates_results(self, mock_context, mock_popularity, mock_counts) -> None:
        sellers = {
            f"seller-{index}": _seller_with_name(f"Tienda {index:02d}", seller_id=f"seller-{index}")
            for index in range(3)
        }
        mock_context.return_value = self._mock_context(sellers)
        mock_popularity.return_value = {seller_id: index for seller_id, index in zip(sellers, [0, 1, 2])}
        mock_counts.return_value = {seller_id: {"published": 1} for seller_id in sellers}

        page = await list_businesses(
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            limit=2,
            offset=0,
        )

        self.assertEqual(len(page.businesses), 2)
        self.assertEqual(page.total_businesses, 3)
        self.assertTrue(page.has_more)
        self.assertEqual(page.businesses[0].store.store_name, "Tienda 02")

    @patch.object(marketplace_service, "aggregate_product_counts_by_seller", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_aggregate_seller_popularity", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_build_marketplace_seller_context", new_callable=AsyncMock)
    async def test_returns_empty_when_no_visible_sellers(self, mock_context, mock_popularity, mock_counts) -> None:
        mock_context.return_value = ({}, [], [], [])
        mock_popularity.return_value = {}
        mock_counts.return_value = {}

        result = await list_businesses(
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            limit=20,
            offset=0,
        )

        self.assertEqual(result.businesses, [])
        self.assertEqual(result.total_businesses, 0)
        self.assertFalse(result.has_more)
        mock_popularity.assert_not_called()
        mock_counts.assert_not_called()

    @patch.object(marketplace_service, "aggregate_product_counts_by_seller", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_aggregate_seller_popularity", new_callable=AsyncMock)
    @patch.object(marketplace_service, "_build_marketplace_seller_context", new_callable=AsyncMock)
    async def test_excludes_sellers_without_listable_products(
        self,
        mock_context,
        mock_popularity,
        mock_counts,
    ) -> None:
        sellers = {
            "seller-with-products": _seller_with_name("Con productos", seller_id="seller-with-products"),
            "seller-empty": _seller_with_name("Vacía", seller_id="seller-empty"),
            "seller-view-only": _seller_with_name("Solo vista", seller_id="seller-view-only"),
        }
        mock_context.return_value = self._mock_context(sellers)
        mock_popularity.return_value = {seller_id: 1 for seller_id in sellers}
        mock_counts.return_value = {
            "seller-with-products": {"published": 2, "view_only": 0},
            "seller-empty": {"published": 0, "view_only": 0},
            "seller-view-only": {"published": 0, "view_only": 3},
        }

        result = await list_businesses(
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            limit=20,
            offset=0,
        )

        names = {item.store.store_name for item in result.businesses}
        self.assertEqual(names, {"Con productos", "Solo vista"})
        self.assertEqual(result.businesses[1].published_product_count, 3)

    async def test_rejects_short_query_without_category(self) -> None:
        with self.assertRaises(ValueError):
            await list_businesses(
                PROVINCE_ID,
                SELLER_MUNICIPALITY_ID,
                query="a",
                limit=20,
                offset=0,
            )


if __name__ == "__main__":
    unittest.main()
