"""Zonas de venta del producto: visibilidad en catálogo público por municipio."""

from __future__ import annotations

import json
import unittest

from test_e2e.products.utils.fixtures import (
    cleanup_db,
    headers_for,
    photo_upload,
    product_form,
    seed_seller,
)
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured
from test_e2e.utils.locations import EXTRA_MUNICIPALITY_ID, PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARIANAO_AREA = {
    "province_id": PROVINCE_ID,
    "municipality_id": EXTRA_MUNICIPALITY_ID,
}


def _public_product_ids(payload: dict) -> set[str]:
    return {
        product["id"]
        for section in payload.get("sections") or []
        for product in section.get("products") or []
    }


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ProductSalesAreasE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_new_product_defaults_to_all_profile_sales_zones(self) -> None:
        seller = seed_seller(plan_tier="standard", extra_sales_zone=True)
        headers = headers_for(seller)

        with api_client() as client:
            category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers,
                json={"name": "Zonas default"},
            )
            self.assertEqual(category.status_code, 201, category.text)
            created = client.post(
                "/api/auth/me/catalog/products",
                headers=headers,
                data=product_form(name="Harina", category_id=category.json()["id"]),
                files={"photo": photo_upload()},
            )
            self.assertEqual(created.status_code, 201, created.text)
            zones = [area["municipality_id"] for area in created.json().get("sales_areas") or []]
            self.assertEqual(zones, [SELLER_MUNICIPALITY_ID, EXTRA_MUNICIPALITY_ID])

    def test_product_without_delivery_stays_visible_only_in_selected_sales_zone(self) -> None:
        seller = seed_seller(plan_tier="standard", extra_sales_zone=True)
        headers = headers_for(seller)

        with api_client() as client:
            category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers,
                json={"name": "Zonas recorte"},
            )
            self.assertEqual(category.status_code, 201, category.text)
            created = client.post(
                "/api/auth/me/catalog/products",
                headers=headers,
                data=product_form(
                    name="Frijoles",
                    category_id=category.json()["id"],
                    offers_delivery=False,
                    sales_areas=json.dumps([MARIANAO_AREA]),
                ),
                files={"photo": photo_upload()},
            )
            self.assertEqual(created.status_code, 201, created.text)
            product = created.json()
            self.assertFalse(product["offers_delivery"])
            self.assertEqual(
                [area["municipality_id"] for area in product.get("sales_areas") or []],
                [EXTRA_MUNICIPALITY_ID],
            )

            visible = client.get(
                f"/api/marketplace/stores/{seller['store_slug']}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": EXTRA_MUNICIPALITY_ID,
                },
            )
            self.assertEqual(visible.status_code, 200, visible.text)
            self.assertIn(product["id"], _public_product_ids(visible.json()))

            hidden = client.get(
                f"/api/marketplace/stores/{seller['store_slug']}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": SELLER_MUNICIPALITY_ID,
                },
            )
            self.assertEqual(hidden.status_code, 200, hidden.text)
            self.assertNotIn(product["id"], _public_product_ids(hidden.json()))
