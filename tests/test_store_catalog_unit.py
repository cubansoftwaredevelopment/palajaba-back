from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from app.services.marketplace import (
    _product_pickup_info,
    _product_to_public,
    _seller_store_product_query,
    _store_catalog_category_docs,
)
from tests.helpers import PROVINCE_ID, REMOTE_MUNICIPALITY_ID, SELLER_MUNICIPALITY_ID, seller_document
from tests.helpers_store_catalog import product_document


class SellerStoreProductQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seller = seller_document()
        self.seller_id = str(self.seller["_id"])

    def test_local_buyer_query_filters_available_products(self) -> None:
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertEqual(
            query,
            {"seller_id": self.seller_id, "is_available": True},
        )

    def test_remote_buyer_query_matches_local_buyer(self) -> None:
        local = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        remote = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertEqual(local, remote)

    def test_remote_buyer_query_does_not_filter_delivery_or_view_only(self) -> None:
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertNotIn("$or", query)
        self.assertNotIn("view_only", query)
        self.assertNotIn("offers_delivery", query)

    def test_query_keeps_category_filter(self) -> None:
        category_id = ObjectId()
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
            extra={"category_id": category_id},
        )
        self.assertEqual(query["category_id"], category_id)
        self.assertEqual(query["is_available"], True)

    def test_query_merges_extra_filters(self) -> None:
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            extra={"name": "Arroz"},
        )
        self.assertEqual(query["name"], "Arroz")

    def test_pickup_only_seller_does_not_change_query(self) -> None:
        pickup_seller = seller_document()
        pickup_seller["offers_delivery"] = False
        pickup_seller["delivery_areas"] = []
        query = _seller_store_product_query(
            str(pickup_seller["_id"]),
            pickup_seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertEqual(query["is_available"], True)
        self.assertNotIn("$or", query)

    def test_query_without_extra_has_only_base_keys(self) -> None:
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertEqual(set(query.keys()), {"seller_id", "is_available"})


class ProductPickupInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seller = seller_document()

    def test_local_buyer_never_requires_pickup(self) -> None:
        product = product_document(
            seller_id=str(self.seller["_id"]),
            category_id=ObjectId(),
            name="Pickup",
            offers_delivery=False,
        )
        required, municipality = _product_pickup_info(
            product,
            self.seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertFalse(required)
        self.assertIsNone(municipality)

    def test_remote_buyer_with_delivery_product_has_no_pickup(self) -> None:
        product = product_document(
            seller_id=str(self.seller["_id"]),
            category_id=ObjectId(),
            name="Delivery",
            offers_delivery=True,
        )
        required, municipality = _product_pickup_info(
            product,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertFalse(required)
        self.assertIsNone(municipality)

    def test_remote_buyer_with_pickup_only_product_requires_pickup(self) -> None:
        product = product_document(
            seller_id=str(self.seller["_id"]),
            category_id=ObjectId(),
            name="Pickup",
            offers_delivery=False,
        )
        required, municipality = _product_pickup_info(
            product,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertTrue(required)
        self.assertEqual(municipality, "Playa")

    def test_missing_offers_delivery_field_treated_as_pickup_for_remote(self) -> None:
        product = product_document(
            seller_id=str(self.seller["_id"]),
            category_id=ObjectId(),
            name="Legacy",
            include_offers_delivery_field=False,
        )
        required, _ = _product_pickup_info(
            product,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertTrue(required)

    def test_view_only_without_delivery_still_marks_pickup_for_remote(self) -> None:
        product = product_document(
            seller_id=str(self.seller["_id"]),
            category_id=ObjectId(),
            name="View only",
            view_only=True,
            offers_delivery=False,
        )
        required, municipality = _product_pickup_info(
            product,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertTrue(required)
        self.assertEqual(municipality, "Playa")

    def test_seller_without_delivery_areas_marks_pickup_for_remote(self) -> None:
        seller = seller_document()
        seller["offers_delivery"] = False
        seller["delivery_areas"] = []
        product = product_document(
            seller_id=str(seller["_id"]),
            category_id=ObjectId(),
            name="Pickup",
            offers_delivery=True,
        )
        required, _ = _product_pickup_info(
            product,
            seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertTrue(required)


class ProductToPublicStoreCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seller = seller_document()
        self.seller_id = str(self.seller["_id"])

    def test_remote_pickup_only_includes_pickup_notice(self) -> None:
        product = product_document(
            seller_id=self.seller_id,
            category_id=ObjectId(),
            name="Pickup",
            offers_delivery=False,
        )
        public = _product_to_public(
            product,
            {self.seller_id: self.seller},
            buyer_province_id=PROVINCE_ID,
            buyer_municipality_id=REMOTE_MUNICIPALITY_ID,
        )
        self.assertIsNotNone(public)
        assert public is not None
        self.assertTrue(public.pickup_required)
        self.assertIn("Recoger en", public.pickup_notice or "")

    def test_local_buyer_has_no_pickup_notice(self) -> None:
        product = product_document(
            seller_id=self.seller_id,
            category_id=ObjectId(),
            name="Pickup",
            offers_delivery=False,
        )
        public = _product_to_public(
            product,
            {self.seller_id: self.seller},
            buyer_province_id=PROVINCE_ID,
            buyer_municipality_id=SELLER_MUNICIPALITY_ID,
        )
        self.assertIsNotNone(public)
        assert public is not None
        self.assertFalse(public.pickup_required)
        self.assertIsNone(public.pickup_notice)

    def test_view_only_flag_is_preserved(self) -> None:
        product = product_document(
            seller_id=self.seller_id,
            category_id=ObjectId(),
            name="View only",
            view_only=True,
            offers_delivery=False,
        )
        public = _product_to_public(
            product,
            {self.seller_id: self.seller},
            buyer_province_id=PROVINCE_ID,
            buyer_municipality_id=REMOTE_MUNICIPALITY_ID,
        )
        self.assertIsNotNone(public)
        assert public is not None
        self.assertTrue(public.view_only)

    def test_delivery_product_remote_has_no_pickup_notice(self) -> None:
        product = product_document(
            seller_id=self.seller_id,
            category_id=ObjectId(),
            name="Delivery",
            offers_delivery=True,
        )
        public = _product_to_public(
            product,
            {self.seller_id: self.seller},
            buyer_province_id=PROVINCE_ID,
            buyer_municipality_id=REMOTE_MUNICIPALITY_ID,
        )
        self.assertIsNotNone(public)
        assert public is not None
        self.assertFalse(public.pickup_required)

    def test_missing_seller_returns_none(self) -> None:
        product = product_document(
            seller_id="missing-seller",
            category_id=ObjectId(),
            name="Orphan",
            offers_delivery=True,
        )
        public = _product_to_public(product, {})
        self.assertIsNone(public)

    def test_unavailable_product_still_serializes_when_passed_in(self) -> None:
        product = product_document(
            seller_id=self.seller_id,
            category_id=ObjectId(),
            name="Unavailable",
            is_available=False,
        )
        public = _product_to_public(
            product,
            {self.seller_id: self.seller},
            buyer_province_id=PROVINCE_ID,
            buyer_municipality_id=REMOTE_MUNICIPALITY_ID,
        )
        self.assertIsNotNone(public)
        assert public is not None
        self.assertFalse(public.is_available)


class StoreCatalogCategoryDocsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.seller = seller_document()
        self.seller_id = str(self.seller["_id"])

    async def test_returns_existing_categories_when_present(self) -> None:
        category_id = ObjectId()
        category_doc = {
            "_id": category_id,
            "seller_id": self.seller_id,
            "name": "Bebidas",
            "sort_order": 0,
        }
        categories_col = MagicMock()
        categories_col.find.return_value.sort.return_value.to_list = AsyncMock(
            return_value=[category_doc]
        )
        products_col = MagicMock()
        products_col.distinct = AsyncMock(return_value=[category_id])

        with patch(
            "app.services.marketplace.get_catalog_categories_collection",
            return_value=categories_col,
        ), patch(
            "app.services.marketplace.get_catalog_products_collection",
            return_value=products_col,
        ):
            docs = await _store_catalog_category_docs(
                self.seller_id,
                self.seller,
                PROVINCE_ID,
                REMOTE_MUNICIPALITY_ID,
            )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Bebidas")

    async def test_appends_orphan_category_as_otros(self) -> None:
        known_id = ObjectId()
        orphan_id = ObjectId()
        categories_col = MagicMock()
        categories_col.find.return_value.sort.return_value.to_list = AsyncMock(
            return_value=[
                {
                    "_id": known_id,
                    "seller_id": self.seller_id,
                    "name": "Comida",
                    "sort_order": 0,
                }
            ]
        )
        products_col = MagicMock()
        products_col.distinct = AsyncMock(return_value=[known_id, orphan_id, None])

        with patch(
            "app.services.marketplace.get_catalog_categories_collection",
            return_value=categories_col,
        ), patch(
            "app.services.marketplace.get_catalog_products_collection",
            return_value=products_col,
        ):
            docs = await _store_catalog_category_docs(
                self.seller_id,
                self.seller,
                PROVINCE_ID,
                REMOTE_MUNICIPALITY_ID,
            )

        names = [doc["name"] for doc in docs]
        self.assertIn("Comida", names)
        self.assertIn("Otros", names)
        self.assertEqual(len(docs), 2)

    async def test_returns_empty_when_no_categories_and_no_products(self) -> None:
        categories_col = MagicMock()
        categories_col.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
        products_col = MagicMock()
        products_col.count_documents = AsyncMock(return_value=0)

        with patch(
            "app.services.marketplace.get_catalog_categories_collection",
            return_value=categories_col,
        ), patch(
            "app.services.marketplace.get_catalog_products_collection",
            return_value=products_col,
        ):
            docs = await _store_catalog_category_docs(
                self.seller_id,
                self.seller,
                PROVINCE_ID,
                REMOTE_MUNICIPALITY_ID,
            )

        self.assertEqual(docs, [])

    async def test_returns_fallback_catalog_when_products_exist_without_categories(self) -> None:
        categories_col = MagicMock()
        categories_col.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
        products_col = MagicMock()
        products_col.count_documents = AsyncMock(return_value=3)

        with patch(
            "app.services.marketplace.get_catalog_categories_collection",
            return_value=categories_col,
        ), patch(
            "app.services.marketplace.get_catalog_products_collection",
            return_value=products_col,
        ):
            docs = await _store_catalog_category_docs(
                self.seller_id,
                self.seller,
                PROVINCE_ID,
                REMOTE_MUNICIPALITY_ID,
            )

        self.assertEqual(len(docs), 1)
        self.assertIsNone(docs[0]["_id"])
        self.assertEqual(docs[0]["name"], "Catálogo")

    async def test_does_not_duplicate_known_orphan_ids(self) -> None:
        category_id = ObjectId()
        categories_col = MagicMock()
        categories_col.find.return_value.sort.return_value.to_list = AsyncMock(
            return_value=[
                {
                    "_id": category_id,
                    "seller_id": self.seller_id,
                    "name": "Comida",
                    "sort_order": 0,
                }
            ]
        )
        products_col = MagicMock()
        products_col.distinct = AsyncMock(return_value=[category_id])

        with patch(
            "app.services.marketplace.get_catalog_categories_collection",
            return_value=categories_col,
        ), patch(
            "app.services.marketplace.get_catalog_products_collection",
            return_value=products_col,
        ):
            docs = await _store_catalog_category_docs(
                self.seller_id,
                self.seller,
                PROVINCE_ID,
                REMOTE_MUNICIPALITY_ID,
            )

        self.assertEqual(len(docs), 1)


if __name__ == "__main__":
    unittest.main()
