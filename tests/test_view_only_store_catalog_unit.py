from __future__ import annotations

import unittest
from bson import ObjectId

from app.services.marketplace import (
    _marketplace_product_query,
    _product_to_public,
    _seller_store_product_query,
)
from tests.helpers import (
    PROVINCE_ID,
    REMOTE_MUNICIPALITY_ID,
    SELLER_MUNICIPALITY_ID,
    STORE_SLUG,
    product_document,
    seller_document,
)


class SellerStoreProductQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seller = seller_document()
        self.seller_id = str(self.seller["_id"])

    def test_local_buyer_query_does_not_filter_view_only_or_delivery(self) -> None:
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertEqual(query, {"seller_id": self.seller_id})

    def test_remote_buyer_query_allows_delivery_or_view_only(self) -> None:
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertEqual(query["seller_id"], self.seller_id)
        self.assertEqual(
            query["$or"],
            [{"offers_delivery": True}, {"view_only": True}],
        )
        self.assertNotIn("view_only", query)
        self.assertNotIn("offers_delivery", query)

    def test_remote_buyer_query_keeps_category_filter(self) -> None:
        category_id = ObjectId()
        query = _seller_store_product_query(
            self.seller_id,
            self.seller,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
            extra={"category_id": category_id},
        )
        self.assertEqual(query["category_id"], category_id)
        self.assertIn("$or", query)


class MarketplaceProductQueryTests(unittest.TestCase):
    def test_marketplace_still_excludes_view_only(self) -> None:
        query = _marketplace_product_query(["seller-1"], [])
        self.assertEqual(query["view_only"], {"$ne": True})
        self.assertEqual(query["is_available"], True)


class ProductToPublicTests(unittest.TestCase):
    def test_preserves_view_only_flag(self) -> None:
        seller = seller_document()
        seller_id = str(seller["_id"])
        product = product_document(
            seller_id=seller_id,
            category_id=ObjectId(),
            name="Arroz solo vista",
            view_only=True,
            offers_delivery=False,
        )
        product["_id"] = ObjectId()

        public = _product_to_public(
            product,
            {seller_id: seller},
            buyer_province_id=PROVINCE_ID,
            buyer_municipality_id=REMOTE_MUNICIPALITY_ID,
        )

        self.assertIsNotNone(public)
        assert public is not None
        self.assertTrue(public.view_only)
        self.assertFalse(public.offers_delivery)


if __name__ == "__main__":
    unittest.main()
