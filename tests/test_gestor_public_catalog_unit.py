from __future__ import annotations

import unittest

from bson import ObjectId

from app.schemas.marketplace import (
    MarketplaceGestorProductPublic,
    MarketplaceProductPublic,
    MarketplaceStoreCatalogPublic,
    MarketplaceStorePublic,
)
from app.services.marketplace import apply_gestor_to_marketplace_product


class MarketplaceGestorIsolationTests(unittest.TestCase):
    def test_marketplace_product_schema_has_no_gestor_fields(self) -> None:
        store = MarketplaceStorePublic(
            id="seller1",
            store_name="Mi Tienda",
            store_slug="mi-tienda",
            phone="+5351111111",
        )
        product = MarketplaceProductPublic(
            id="p1",
            global_category_id="otros",
            name="Arroz",
            image_url="https://example.com/a.jpg",
            base_price=100.0,
            base_currency="CUP",
            offers_delivery=True,
            store=store,
            category_name="Otros",
        )
        payload = product.model_dump()
        self.assertNotIn("gestor_id", payload)
        self.assertNotIn("gestor_username", payload)

    def test_store_catalog_schema_has_no_gestor_field(self) -> None:
        fields = MarketplaceStoreCatalogPublic.model_fields
        self.assertNotIn("gestor", fields)

    def test_apply_gestor_returns_gestor_product_without_mutating_base_schema(self) -> None:
        store = MarketplaceStorePublic(
            id="seller1",
            store_name="Mi Tienda",
            store_slug="mi-tienda",
            phone="+5351111111",
        )
        product = MarketplaceProductPublic(
            id="p1",
            global_category_id="otros",
            name="Arroz",
            image_url="https://example.com/a.jpg",
            base_price=100.0,
            base_currency="CUP",
            offers_delivery=True,
            store=store,
            category_name="Otros",
        )
        seller_doc = {
            "_id": ObjectId(),
            "store_name": "Mi Tienda",
            "store_slug": "mi-tienda",
            "phone": "51111111",
            "profile_photo_url": None,
            "business_area": None,
        }
        gestor = {
            "_id": ObjectId(),
            "username": "pepe_venta",
            "phone": "52222222",
        }

        result = apply_gestor_to_marketplace_product(
            product,
            seller=seller_doc,
            gestor=gestor,
            margin_amount=25,
        )

        self.assertIsInstance(result, MarketplaceGestorProductPublic)
        self.assertEqual(result.base_price, 125.0)
        self.assertEqual(result.gestor_username, "pepe_venta")
        # El producto base del marketplace no cambia
        self.assertEqual(product.base_price, 100.0)
        self.assertNotIn("gestor_id", product.model_dump())


if __name__ == "__main__":
    unittest.main()
