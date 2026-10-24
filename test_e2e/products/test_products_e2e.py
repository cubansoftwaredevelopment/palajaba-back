"""Recorrido de catálogo: categorías, productos, descuento y listado admin."""

from __future__ import annotations

import unittest

from app.products.utils import PRODUCT_DISCOUNT_PLAN_REQUIRED_MESSAGE
from test_e2e.products.utils.fixtures import (
    cleanup_db,
    headers_for,
    photo_upload,
    product_form,
    seed_seller,
)
from test_e2e.utils.api import admin_auth_headers, api_client
from test_e2e.utils.database import mongo_configured
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ProductsE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_seller_creates_category_and_product_then_sees_them_in_catalog(self) -> None:
        seller = seed_seller(plan_tier="standard")
        headers = headers_for(seller)

        with api_client() as client:
            created_category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers,
                json={"name": "Despensa"},
            )
            self.assertEqual(created_category.status_code, 201, created_category.text)
            category = created_category.json()
            self.assertEqual(category["name"], "Despensa")
            self.assertEqual(category["product_count"], 0)

            created_product = client.post(
                "/api/auth/me/catalog/products",
                headers=headers,
                data=product_form(name="Arroz", category_id=category["id"], base_price=250),
                files={"photo": photo_upload()},
            )
            self.assertEqual(created_product.status_code, 201, created_product.text)
            product = created_product.json()
            self.assertEqual(product["name"], "Arroz")
            self.assertEqual(product["base_price"], 250)
            self.assertEqual(product["base_currency"], "CUP")
            self.assertIsNone(product.get("discount_percent"))
            self.assertTrue(product["is_available"])

            catalog = client.get("/api/auth/me/catalog", headers=headers)
            self.assertEqual(catalog.status_code, 200, catalog.text)
            summary = catalog.json()
            self.assertEqual(summary["total_products"], 1)
            self.assertEqual(summary["categories"][0]["name"], "Despensa")
            self.assertEqual(summary["categories"][0]["products"][0]["id"], product["id"])

            admin_list = client.get("/api/admin/products", headers=admin_auth_headers())
            self.assertEqual(admin_list.status_code, 200, admin_list.text)
            ids = {row["id"] for row in admin_list.json()["products"]}
            self.assertIn(product["id"], ids)

    def test_standard_seller_cannot_save_product_discount(self) -> None:
        seller = seed_seller(plan_tier="standard")
        headers = headers_for(seller)

        with api_client() as client:
            category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers,
                json={"name": "Ofertas"},
            ).json()
            response = client.post(
                "/api/auth/me/catalog/products",
                headers=headers,
                data=product_form(
                    name="Café",
                    category_id=category["id"],
                    discount_percent="20",
                ),
                files={"photo": photo_upload()},
            )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], PRODUCT_DISCOUNT_PLAN_REQUIRED_MESSAGE)

    def test_pro_trial_and_premium_sellers_can_save_product_discount(self) -> None:
        pro = seed_seller(plan_tier="pro")
        trial = seed_seller(plan_tier="standard", is_trial=True)
        premium = seed_seller(plan_tier="premium")

        with api_client() as client:
            pro_category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers_for(pro),
                json={"name": "Pro"},
            ).json()
            pro_product = client.post(
                "/api/auth/me/catalog/products",
                headers=headers_for(pro),
                data=product_form(
                    name="Aceite Pro",
                    category_id=pro_category["id"],
                    discount_percent="15",
                ),
                files={"photo": photo_upload()},
            )
            self.assertEqual(pro_product.status_code, 201, pro_product.text)
            self.assertEqual(pro_product.json()["discount_percent"], 15)

            trial_category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers_for(trial),
                json={"name": "Prueba"},
            ).json()
            trial_product = client.post(
                "/api/auth/me/catalog/products",
                headers=headers_for(trial),
                data=product_form(
                    name="Aceite Prueba",
                    category_id=trial_category["id"],
                    discount_percent="10",
                ),
                files={"photo": photo_upload()},
            )
            self.assertEqual(trial_product.status_code, 201, trial_product.text)
            self.assertEqual(trial_product.json()["discount_percent"], 10)

            premium_category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers_for(premium),
                json={"name": "Premium"},
            ).json()
            premium_product = client.post(
                "/api/auth/me/catalog/products",
                headers=headers_for(premium),
                data=product_form(
                    name="Aceite Premium",
                    category_id=premium_category["id"],
                    discount_percent="15",
                ),
                files={"photo": photo_upload()},
            )
            self.assertEqual(premium_product.status_code, 201, premium_product.text)
            self.assertEqual(premium_product.json()["discount_percent"], 15)

            updated = client.patch(
                f"/api/auth/me/catalog/products/{premium_product.json()['id']}",
                headers=headers_for(premium),
                data=product_form(
                    name="Aceite Premium",
                    category_id=premium_category["id"],
                    discount_percent="25",
                ),
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["discount_percent"], 25)

    def test_premium_product_discount_hides_after_downgrade_to_basic(self) -> None:
        seller = seed_seller(plan_tier="premium")
        headers = headers_for(seller)
        admin = admin_auth_headers()

        with api_client() as client:
            category = client.post(
                "/api/auth/me/catalog/categories",
                headers=headers,
                json={"name": "Ofertas Premium"},
            )
            self.assertEqual(category.status_code, 201, category.text)
            category_id = category.json()["id"]

            created = client.post(
                "/api/auth/me/catalog/products",
                headers=headers,
                data=product_form(
                    name="Banderas",
                    category_id=category_id,
                    base_price=34,
                    discount_percent="10",
                ),
                files={"photo": photo_upload()},
            )
            self.assertEqual(created.status_code, 201, created.text)
            product_id = created.json()["id"]
            self.assertEqual(created.json()["discount_percent"], 10)

            me = client.get("/api/auth/me", headers=headers)
            self.assertEqual(me.status_code, 200, me.text)
            self.assertTrue(me.json()["has_product_discounts"])
            self._assert_catalog_discount(client, headers, product_id, 10)
            self._assert_public_catalog_discount(client, seller["store_slug"], 10)

            basic = client.patch(
                f"/api/admin/registrations/{seller['seller_id']}/subscription",
                headers=admin,
                json={
                    "plan_tier": "standard",
                    "billing_period": "monthly",
                    "keep_gestor_ids": [],
                },
            )
            self.assertEqual(basic.status_code, 200, basic.text)
            self.assertEqual(basic.json()["plan_tier"], "standard")
            me = client.get("/api/auth/me", headers=headers)
            self.assertEqual(me.status_code, 200, me.text)
            self.assertFalse(me.json()["has_product_discounts"])
            self._assert_catalog_discount(client, headers, product_id, None)
            self._assert_public_catalog_discount(client, seller["store_slug"], None)

            pro = client.patch(
                f"/api/admin/registrations/{seller['seller_id']}/subscription",
                headers=admin,
                json={
                    "plan_tier": "pro",
                    "billing_period": "monthly",
                    "keep_gestor_ids": [],
                },
            )
            self.assertEqual(pro.status_code, 200, pro.text)
            self.assertEqual(pro.json()["plan_tier"], "pro")
            me = client.get("/api/auth/me", headers=headers)
            self.assertEqual(me.status_code, 200, me.text)
            self.assertTrue(me.json()["has_product_discounts"])
            self._assert_catalog_discount(client, headers, product_id, 10)
            self._assert_public_catalog_discount(client, seller["store_slug"], 10)

    def _assert_catalog_discount(self, client, headers, product_id: str, expected: int | None) -> None:
        catalog = client.get("/api/auth/me/catalog", headers=headers)
        self.assertEqual(catalog.status_code, 200, catalog.text)
        products = [
            product
            for category in catalog.json()["categories"]
            for product in category.get("products") or []
            if product["id"] == product_id
        ]
        self.assertEqual(len(products), 1, catalog.text)
        self.assertEqual(products[0].get("discount_percent"), expected)

    def _assert_public_catalog_discount(self, client, store_slug: str, expected: int | None) -> None:
        public = client.get(
            f"/api/marketplace/stores/{store_slug}/catalog",
            params={
                "province_id": PROVINCE_ID,
                "municipality_id": SELLER_MUNICIPALITY_ID,
            },
        )
        self.assertEqual(public.status_code, 200, public.text)
        products = [
            product
            for section in public.json().get("sections") or []
            for product in section.get("products") or []
        ]
        self.assertEqual(len(products), 1, public.text)
        self.assertEqual(products[0].get("discount_percent"), expected)
