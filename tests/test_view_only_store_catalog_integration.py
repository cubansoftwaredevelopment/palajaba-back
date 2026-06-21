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
from app.services.marketplace import (
    _build_marketplace_products_query,
    _get_visible_sellers,
    _split_sellers_by_locality,
    get_store_catalog,
    list_store_category_products,
)
from tests.helpers import (
    MARKER,
    PRODUCT_PURCHASABLE_NO_DELIVERY,
    PRODUCT_PURCHASABLE_WITH_DELIVERY,
    PRODUCT_VIEW_ONLY,
    PROVINCE_ID,
    REMOTE_MUNICIPALITY_ID,
    SELLER_MUNICIPALITY_ID,
    STORE_NAME,
    STORE_SLUG,
    product_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


async def cleanup_view_only_test_data() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()
    await products.delete_many({"view_only_store_catalog_test_marker": MARKER})
    await categories.delete_many({"view_only_store_catalog_test_marker": MARKER})
    await registrations.delete_many({"store_name": STORE_NAME})


async def seed_view_only_test_data() -> dict[str, ObjectId | str]:
    seller_oid = ObjectId()
    category_id = ObjectId()
    view_only_id = ObjectId()
    no_delivery_id = ObjectId()
    with_delivery_id = ObjectId()
    seller_id = str(seller_oid)

    registrations = get_registrations_collection()
    categories = get_catalog_categories_collection()
    products = get_catalog_products_collection()

    await registrations.insert_one(seller_document(seller_oid))
    await categories.insert_one(
        {
            "_id": category_id,
            "seller_id": seller_id,
            "name": "Categoría prueba view only",
            "sort_order": 0,
            "view_only_store_catalog_test_marker": MARKER,
        }
    )

    docs = [
        (view_only_id, PRODUCT_VIEW_ONLY, True, False),
        (no_delivery_id, PRODUCT_PURCHASABLE_NO_DELIVERY, False, False),
        (with_delivery_id, PRODUCT_PURCHASABLE_WITH_DELIVERY, False, True),
    ]
    for product_id, name, view_only, offers_delivery in docs:
        await products.insert_one(
            {
                **product_document(
                    seller_id=seller_id,
                    category_id=category_id,
                    name=name,
                    view_only=view_only,
                    offers_delivery=offers_delivery,
                ),
                "_id": product_id,
            }
        )

    return {
        "seller_id": seller_id,
        "category_id": category_id,
        "view_only_id": view_only_id,
        "no_delivery_id": no_delivery_id,
        "with_delivery_id": with_delivery_id,
    }


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ViewOnlyStoreCatalogIntegrationTests(unittest.IsolatedAsyncioTestCase):
    seller_id: str
    category_id: ObjectId
    view_only_id: ObjectId
    no_delivery_id: ObjectId
    with_delivery_id: ObjectId

    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_view_only_test_data()
        seeded = await seed_view_only_test_data()
        self.seller_id = str(seeded["seller_id"])
        self.category_id = seeded["category_id"]
        self.view_only_id = seeded["view_only_id"]
        self.no_delivery_id = seeded["no_delivery_id"]
        self.with_delivery_id = seeded["with_delivery_id"]

    async def asyncTearDown(self) -> None:
        await cleanup_view_only_test_data()
        await close_mongo_connection()

    def _catalog_product_ids(self, catalog) -> set[str]:
        return {
            product.id
            for section in catalog.sections
            for product in section.products
        }

    async def test_local_buyer_sees_all_catalog_products(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        product_ids = self._catalog_product_ids(catalog)
        self.assertIn(str(self.view_only_id), product_ids)
        self.assertIn(str(self.no_delivery_id), product_ids)
        self.assertIn(str(self.with_delivery_id), product_ids)

    async def test_remote_buyer_sees_all_catalog_products_with_pickup_notice(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        product_ids = self._catalog_product_ids(catalog)

        self.assertIn(str(self.view_only_id), product_ids)
        self.assertIn(str(self.with_delivery_id), product_ids)
        self.assertIn(str(self.no_delivery_id), product_ids)

        pickup_product = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.no_delivery_id)
        )
        self.assertTrue(pickup_product.pickup_required)

        view_only_product = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.view_only_id)
        )
        self.assertTrue(view_only_product.view_only)

    async def test_list_store_category_products_for_remote_buyer(self) -> None:
        page = await list_store_category_products(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
            str(self.category_id),
            limit=20,
            offset=0,
        )
        product_ids = {product.id for product in page.products}
        self.assertIn(str(self.view_only_id), product_ids)
        self.assertIn(str(self.no_delivery_id), product_ids)

    async def test_marketplace_still_hides_view_only_products(self) -> None:
        seller_by_id = await _get_visible_sellers(PROVINCE_ID, REMOTE_MUNICIPALITY_ID)
        self.assertIn(self.seller_id, seller_by_id)

        local_ids, delivery_ids = _split_sellers_by_locality(
            seller_by_id,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        query = _build_marketplace_products_query(local_ids, delivery_ids)
        products = get_catalog_products_collection()

        self.assertEqual(
            await products.count_documents({**query, "_id": self.view_only_id}),
            0,
        )
        self.assertEqual(
            await products.count_documents({**query, "_id": self.with_delivery_id}),
            1,
        )


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ViewOnlyStoreCatalogApiIntegrationTests(unittest.TestCase):
    fixtures: dict[str, ObjectId | str]

    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        async def prepare() -> dict[str, ObjectId | str]:
            await connect_to_mongo()
            await cleanup_view_only_test_data()
            return await seed_view_only_test_data()

        cls.fixtures = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_view_only_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_http_catalog_endpoint_for_remote_buyer(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                f"/api/marketplace/stores/{STORE_SLUG}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": REMOTE_MUNICIPALITY_ID,
                    "limit_per_category": 20,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        product_ids = {
            product["id"]
            for section in payload.get("sections", [])
            for product in section.get("products", [])
        }
        self.assertIn(str(self.fixtures["view_only_id"]), product_ids)
        self.assertIn(str(self.fixtures["with_delivery_id"]), product_ids)
        self.assertIn(str(self.fixtures["no_delivery_id"]), product_ids)

        view_only_payload = next(
            product
            for section in payload["sections"]
            for product in section["products"]
            if product["id"] == str(self.fixtures["view_only_id"])
        )
        self.assertTrue(view_only_payload["view_only"])

    def test_http_category_products_endpoint_for_remote_buyer(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                f"/api/marketplace/stores/{STORE_SLUG}/categories/{self.fixtures['category_id']}/products",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": REMOTE_MUNICIPALITY_ID,
                    "limit": 20,
                    "offset": 0,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        product_ids = {product["id"] for product in response.json().get("products", [])}
        self.assertIn(str(self.fixtures["view_only_id"]), product_ids)
        self.assertIn(str(self.fixtures["no_delivery_id"]), product_ids)


if __name__ == "__main__":
    unittest.main()
