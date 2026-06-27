from __future__ import annotations

import os
import unittest
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.main import app
from app.security import create_seller_token
from app.services import exchange_rates as exchange_rates_service
from app.services.catalog import get_catalog_summary
from app.services.marketplace import list_store_category_products
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID
from tests.helpers_catalog_product_sort import (
    MARKER,
    STORE_NAME,
    category_document,
    product_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def _set_test_exchange_rates() -> None:
    exchange_rates_service._cup_per_unit_cache.update(
        {"CUP": 1.0, "USD": 655.0, "EUR": 750.0, "MLC": 440.0},
    )
    exchange_rates_service._rates_available = True


def _reset_exchange_rates() -> None:
    exchange_rates_service._cup_per_unit_cache = {"CUP": 1.0}
    exchange_rates_service._rates_available = False


class CatalogProductSortSeed:
    seller_id: str
    category_id: ObjectId
    product_alpha_id: ObjectId
    product_beta_id: ObjectId
    product_zeta_id: ObjectId


async def cleanup_catalog_product_sort_test_data() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()
    await products.delete_many({"catalog_product_sort_test_marker": MARKER})
    await categories.delete_many({"catalog_product_sort_test_marker": MARKER})
    await registrations.delete_many({"catalog_product_sort_test_marker": MARKER})


async def seed_catalog_product_sort_test_data() -> CatalogProductSortSeed:
    seed = CatalogProductSortSeed()
    seller_oid = ObjectId()
    seed.seller_id = str(seller_oid)
    seed.category_id = ObjectId()
    seed.product_alpha_id = ObjectId()
    seed.product_beta_id = ObjectId()
    seed.product_zeta_id = ObjectId()

    registrations = get_registrations_collection()
    categories = get_catalog_categories_collection()
    products = get_catalog_products_collection()

    await registrations.insert_one(seller_document(seller_oid))
    await categories.insert_one(
        category_document(
            seller_id=seed.seller_id,
            category_id=seed.category_id,
        )
    )

    product_specs = [
        (seed.product_zeta_id, "Zeta", 300.0, 5, 2),
        (seed.product_alpha_id, "Alpha", 100.0, 20, 0),
        (seed.product_beta_id, "Beta", 200.0, 20, 1),
    ]
    for product_id, name, price, popularity, sort_order in product_specs:
        await products.insert_one(
            product_document(
                seller_id=seed.seller_id,
                category_id=seed.category_id,
                name=name,
                base_price=price,
                popularity=popularity,
                sort_order=sort_order,
            )
            | {"_id": product_id}
        )

    await categories.update_one(
        {"_id": seed.category_id},
        {"$set": {"product_count": len(product_specs)}},
    )
    return seed


def seller_auth_header(seller_id: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=STORE_NAME)
    return {"Authorization": f"Bearer {token}"}


def product_names_from_summary(summary, category_id: str) -> list[str]:
    category = next(item for item in summary.categories if item.id == category_id)
    return [product.name for product in category.products]


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CatalogProductSortServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    seed: CatalogProductSortSeed

    async def asyncSetUp(self) -> None:
        _set_test_exchange_rates()
        await connect_to_mongo()
        await cleanup_catalog_product_sort_test_data()
        self.seed = await seed_catalog_product_sort_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_catalog_product_sort_test_data()
        await close_mongo_connection()
        _reset_exchange_rates()

    async def test_summary_defaults_to_popularity_for_legacy_category(self) -> None:
        summary = await get_catalog_summary(self.seed.seller_id)
        names = product_names_from_summary(summary, str(self.seed.category_id))
        self.assertEqual(names, ["Alpha", "Beta", "Zeta"])

        category = next(item for item in summary.categories if item.id == str(self.seed.category_id))
        self.assertEqual(category.product_sort_mode, "popularity")

    async def test_marketplace_category_products_match_popularity_order(self) -> None:
        page = await list_store_category_products(
            STORE_NAME,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            str(self.seed.category_id),
        )
        self.assertEqual([item.name for item in page.products], ["Alpha", "Beta", "Zeta"])

    async def test_price_sort_converts_mixed_currencies(self) -> None:
        products = get_catalog_products_collection()
        categories = get_catalog_categories_collection()
        usd_product_id = ObjectId()

        await products.insert_one(
            product_document(
                seller_id=self.seed.seller_id,
                category_id=self.seed.category_id,
                name="Premium USD",
                base_price=10.0,
                base_currency="USD",
            )
            | {"_id": usd_product_id}
        )
        await categories.update_one(
            {"_id": self.seed.category_id},
            {"$set": {"product_sort_mode": "price", "product_count": 4}},
        )

        summary = await get_catalog_summary(self.seed.seller_id)
        names = product_names_from_summary(summary, str(self.seed.category_id))
        self.assertEqual(names, ["Alpha", "Beta", "Zeta", "Premium USD"])

        page = await list_store_category_products(
            STORE_NAME,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            str(self.seed.category_id),
        )
        self.assertEqual([item.name for item in page.products], ["Alpha", "Beta", "Zeta", "Premium USD"])


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CatalogProductSortApiIntegrationTests(unittest.TestCase):
    seed: CatalogProductSortSeed

    @classmethod
    def setUpClass(cls) -> None:
        _set_test_exchange_rates()
        import asyncio

        async def prepare() -> CatalogProductSortSeed:
            await connect_to_mongo()
            await cleanup_catalog_product_sort_test_data()
            return await seed_catalog_product_sort_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_catalog_product_sort_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())
        _reset_exchange_rates()

    def _auth(self) -> dict[str, str]:
        return seller_auth_header(self.seed.seller_id)

    def _category_id(self) -> str:
        return str(self.seed.category_id)

    def test_patch_product_sort_mode_price(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                f"/api/auth/me/catalog/categories/{self._category_id()}/product-sort",
                headers=self._auth(),
                json={"product_sort_mode": "price"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        names = [item["name"] for item in response.json()["categories"][0]["products"]]
        self.assertEqual(names, ["Alpha", "Beta", "Zeta"])

    def test_patch_product_sort_mode_alphabetical(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                f"/api/auth/me/catalog/categories/{self._category_id()}/product-sort",
                headers=self._auth(),
                json={"product_sort_mode": "alphabetical"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        names = [item["name"] for item in response.json()["categories"][0]["products"]]
        self.assertEqual(names, ["Alpha", "Beta", "Zeta"])

    def test_manual_reorder_updates_summary(self) -> None:
        category_id = self._category_id()
        auth = self._auth()

        with TestClient(app) as client:
            switch = client.patch(
                f"/api/auth/me/catalog/categories/{category_id}/product-sort",
                headers=auth,
                json={"product_sort_mode": "manual"},
            )
            self.assertEqual(switch.status_code, 200, switch.text)

            reordered = client.put(
                f"/api/auth/me/catalog/categories/{category_id}/products/order",
                headers=auth,
                json={
                    "product_ids": [
                        str(self.seed.product_zeta_id),
                        str(self.seed.product_beta_id),
                        str(self.seed.product_alpha_id),
                    ]
                },
            )
        self.assertEqual(reordered.status_code, 200, reordered.text)
        names = [item["name"] for item in reordered.json()["categories"][0]["products"]]
        self.assertEqual(names, ["Zeta", "Beta", "Alpha"])

    def test_reorder_rejected_when_sort_mode_is_not_manual(self) -> None:
        category_id = self._category_id()
        auth = self._auth()

        with TestClient(app) as client:
            switch = client.patch(
                f"/api/auth/me/catalog/categories/{category_id}/product-sort",
                headers=auth,
                json={"product_sort_mode": "price"},
            )
            self.assertEqual(switch.status_code, 200, switch.text)

            rejected = client.put(
                f"/api/auth/me/catalog/categories/{category_id}/products/order",
                headers=auth,
                json={
                    "product_ids": [
                        str(self.seed.product_alpha_id),
                        str(self.seed.product_beta_id),
                        str(self.seed.product_zeta_id),
                    ]
                },
            )
        self.assertEqual(rejected.status_code, 400, rejected.text)
