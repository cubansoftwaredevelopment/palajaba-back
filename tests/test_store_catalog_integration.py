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
from tests.helpers import PROVINCE_ID, REMOTE_MUNICIPALITY_ID, SELLER_MUNICIPALITY_ID
from tests.helpers_store_catalog import (
    MARKER,
    PRODUCT_NO_OFFERS_FIELD,
    PRODUCT_ORPHAN,
    PRODUCT_PICKUP_ONLY,
    PRODUCT_UNAVAILABLE,
    PRODUCT_VIEW_ONLY,
    PRODUCT_VIEW_ONLY_UNAVAILABLE,
    PRODUCT_WITH_DELIVERY,
    STORE_NAME,
    STORE_NAME_NO_CATEGORIES,
    STORE_NAME_ORPHAN,
    STORE_NAME_PICKUP_ONLY,
    STORE_SLUG,
    STORE_SLUG_NO_CATEGORIES,
    STORE_SLUG_ORPHAN,
    STORE_SLUG_PICKUP_ONLY,
    category_document,
    product_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


class StoreCatalogSeed:
    seller_id: str
    category_id: ObjectId
    view_only_id: ObjectId
    pickup_only_id: ObjectId
    with_delivery_id: ObjectId
    unavailable_id: ObjectId
    view_only_unavailable_id: ObjectId
    pickup_only_seller_id: str
    pickup_only_category_id: ObjectId
    pickup_only_product_id: ObjectId
    no_categories_seller_id: str
    no_categories_product_id: ObjectId
    orphan_seller_id: str
    orphan_category_id: ObjectId
    orphan_product_id: ObjectId
    orphan_known_category_id: ObjectId
    missing_offers_field_id: ObjectId


async def cleanup_store_catalog_test_data() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()
    await products.delete_many({"store_catalog_test_marker": MARKER})
    await categories.delete_many({"store_catalog_test_marker": MARKER})
    await registrations.delete_many({"store_catalog_test_marker": MARKER})


async def seed_store_catalog_test_data() -> StoreCatalogSeed:
    seed = StoreCatalogSeed()

    seller_oid = ObjectId()
    category_id = ObjectId()
    seed.seller_id = str(seller_oid)
    seed.category_id = category_id
    seed.view_only_id = ObjectId()
    seed.pickup_only_id = ObjectId()
    seed.with_delivery_id = ObjectId()
    seed.unavailable_id = ObjectId()
    seed.view_only_unavailable_id = ObjectId()

    registrations = get_registrations_collection()
    categories = get_catalog_categories_collection()
    products = get_catalog_products_collection()

    await registrations.insert_one(seller_document(seller_id=seller_oid))
    await categories.insert_one(
        category_document(seller_id=seed.seller_id, category_id=category_id)
    )

    product_specs = [
        (seed.view_only_id, PRODUCT_VIEW_ONLY, True, False, True),
        (seed.pickup_only_id, PRODUCT_PICKUP_ONLY, False, False, True),
        (seed.with_delivery_id, PRODUCT_WITH_DELIVERY, False, True, True),
        (seed.unavailable_id, PRODUCT_UNAVAILABLE, False, True, False),
        (seed.view_only_unavailable_id, PRODUCT_VIEW_ONLY_UNAVAILABLE, True, False, False),
    ]
    for product_id, name, view_only, offers_delivery, is_available in product_specs:
        await products.insert_one(
            product_document(
                seller_id=seed.seller_id,
                category_id=category_id,
                name=name,
                view_only=view_only,
                offers_delivery=offers_delivery,
                is_available=is_available,
                product_id=product_id,
            )
        )

    pickup_seller_oid = ObjectId()
    pickup_category_id = ObjectId()
    pickup_product_id = ObjectId()
    seed.pickup_only_seller_id = str(pickup_seller_oid)
    seed.pickup_only_category_id = pickup_category_id
    seed.pickup_only_product_id = pickup_product_id

    await registrations.insert_one(
        seller_document(
            seller_id=pickup_seller_oid,
            store_name=STORE_NAME_PICKUP_ONLY,
            store_slug=STORE_SLUG_PICKUP_ONLY,
            offers_delivery=False,
            delivery_to_remote=False,
        )
    )
    await categories.insert_one(
        category_document(
            seller_id=seed.pickup_only_seller_id,
            category_id=pickup_category_id,
            name="Pickup cat",
        )
    )
    await products.insert_one(
        product_document(
            seller_id=seed.pickup_only_seller_id,
            category_id=pickup_category_id,
            name=PRODUCT_PICKUP_ONLY,
            offers_delivery=False,
            product_id=pickup_product_id,
        )
    )

    no_cat_seller_oid = ObjectId()
    no_cat_product_id = ObjectId()
    seed.no_categories_seller_id = str(no_cat_seller_oid)
    seed.no_categories_product_id = no_cat_product_id
    await registrations.insert_one(
        seller_document(
            seller_id=no_cat_seller_oid,
            store_name=STORE_NAME_NO_CATEGORIES,
            store_slug=STORE_SLUG_NO_CATEGORIES,
        )
    )
    orphan_category_for_product = ObjectId()
    await products.insert_one(
        product_document(
            seller_id=seed.no_categories_seller_id,
            category_id=orphan_category_for_product,
            name=PRODUCT_WITH_DELIVERY,
            product_id=no_cat_product_id,
        )
    )

    orphan_seller_oid = ObjectId()
    known_category_id = ObjectId()
    orphan_category_id = ObjectId()
    orphan_product_id = ObjectId()
    seed.orphan_seller_id = str(orphan_seller_oid)
    seed.orphan_known_category_id = known_category_id
    seed.orphan_category_id = orphan_category_id
    seed.orphan_product_id = orphan_product_id

    await registrations.insert_one(
        seller_document(
            seller_id=orphan_seller_oid,
            store_name=STORE_NAME_ORPHAN,
            store_slug=STORE_SLUG_ORPHAN,
        )
    )
    await categories.insert_one(
        category_document(
            seller_id=seed.orphan_seller_id,
            category_id=known_category_id,
            name="Conocida",
        )
    )
    await products.insert_one(
        product_document(
            seller_id=seed.orphan_seller_id,
            category_id=orphan_category_id,
            name=PRODUCT_ORPHAN,
            offers_delivery=False,
            product_id=orphan_product_id,
        )
    )

    missing_field_id = ObjectId()
    await products.insert_one(
        product_document(
            seller_id=seed.seller_id,
            category_id=category_id,
            name=PRODUCT_NO_OFFERS_FIELD,
            include_offers_delivery_field=False,
            product_id=missing_field_id,
        )
    )
    seed.missing_offers_field_id = missing_field_id

    return seed


def _catalog_product_ids(catalog) -> set[str]:
    return {
        product.id
        for section in catalog.sections
        for product in section.products
    }


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class StoreCatalogIntegrationTests(unittest.IsolatedAsyncioTestCase):
    seed: StoreCatalogSeed

    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_store_catalog_test_data()
        self.seed = await seed_store_catalog_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_store_catalog_test_data()
        await close_mongo_connection()

    async def test_local_buyer_sees_available_and_sold_out_products(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.view_only_id), product_ids)
        self.assertIn(str(self.seed.pickup_only_id), product_ids)
        self.assertIn(str(self.seed.with_delivery_id), product_ids)
        self.assertIn(str(self.seed.unavailable_id), product_ids)
        unavailable = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.seed.unavailable_id)
        )
        self.assertFalse(unavailable.is_available)

    async def test_remote_buyer_sees_pickup_only_products(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.pickup_only_id), product_ids)
        self.assertIn(str(self.seed.with_delivery_id), product_ids)
        self.assertIn(str(self.seed.view_only_id), product_ids)

    async def test_remote_buyer_sees_missing_offers_delivery_field(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.missing_offers_field_id), product_ids)

    async def test_remote_pickup_only_product_has_pickup_notice(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        pickup_product = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.seed.pickup_only_id)
        )
        self.assertTrue(pickup_product.pickup_required)
        self.assertIsNotNone(pickup_product.pickup_notice)

    async def test_remote_delivery_product_has_no_pickup_notice(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        delivery_product = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.seed.with_delivery_id)
        )
        self.assertFalse(delivery_product.pickup_required)

    async def test_unavailable_products_appear_as_sold_out(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.unavailable_id), product_ids)
        unavailable = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.seed.unavailable_id)
        )
        self.assertFalse(unavailable.is_available)

    async def test_view_only_unavailable_product_appears_in_catalog(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        product = next(
            item
            for section in catalog.sections
            for item in section.products
            if item.id == str(self.seed.view_only_unavailable_id)
        )
        self.assertTrue(product.view_only)
        self.assertFalse(product.is_available)

    async def test_pickup_only_store_visible_for_remote_buyer(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG_PICKUP_ONLY,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.pickup_only_product_id), product_ids)
        self.assertGreater(catalog.total_products, 0)

    async def test_store_without_categories_uses_catalog_fallback(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG_NO_CATEGORIES,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertEqual(len(catalog.sections), 1)
        self.assertEqual(catalog.sections[0].category_name, "Catálogo")
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.no_categories_product_id), product_ids)

    async def test_orphan_category_products_appear_under_otros(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG_ORPHAN,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        section_names = {section.category_name for section in catalog.sections}
        self.assertIn("Otros", section_names)
        product_ids = _catalog_product_ids(catalog)
        self.assertIn(str(self.seed.orphan_product_id), product_ids)

    async def test_list_store_category_products_local_includes_pickup_only(self) -> None:
        page = await list_store_category_products(
            STORE_SLUG,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
            str(self.seed.category_id),
            limit=20,
            offset=0,
        )
        product_ids = {product.id for product in page.products}
        self.assertIn(str(self.seed.pickup_only_id), product_ids)

    async def test_list_store_category_products_remote_includes_pickup_only(self) -> None:
        page = await list_store_category_products(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
            str(self.seed.category_id),
            limit=20,
            offset=0,
        )
        product_ids = {product.id for product in page.products}
        self.assertIn(str(self.seed.pickup_only_id), product_ids)
        self.assertIn(str(self.seed.unavailable_id), product_ids)
        unavailable = next(
            product for product in page.products if product.id == str(self.seed.unavailable_id)
        )
        self.assertFalse(unavailable.is_available)

    async def test_list_store_category_products_reports_total_including_unavailable(self) -> None:
        page = await list_store_category_products(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
            str(self.seed.category_id),
            limit=20,
            offset=0,
        )
        self.assertGreaterEqual(page.total_products, 5)
        product_ids = {product.id for product in page.products}
        self.assertIn(str(self.seed.unavailable_id), product_ids)

    async def test_marketplace_still_hides_pickup_only_for_remote(self) -> None:
        seller_by_id = await _get_visible_sellers(PROVINCE_ID, REMOTE_MUNICIPALITY_ID)
        local_ids, delivery_ids = _split_sellers_by_locality(
            seller_by_id,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        query = _build_marketplace_products_query(local_ids, delivery_ids)
        products = get_catalog_products_collection()
        self.assertEqual(
            await products.count_documents({**query, "_id": self.seed.pickup_only_id}),
            0,
        )

    async def test_marketplace_still_hides_unavailable_products(self) -> None:
        seller_by_id = await _get_visible_sellers(PROVINCE_ID, REMOTE_MUNICIPALITY_ID)
        local_ids, delivery_ids = _split_sellers_by_locality(
            seller_by_id,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        query = _build_marketplace_products_query(local_ids, delivery_ids)
        products = get_catalog_products_collection()
        self.assertEqual(
            await products.count_documents({**query, "_id": self.seed.unavailable_id}),
            0,
        )

    async def test_marketplace_still_hides_view_only_for_remote(self) -> None:
        seller_by_id = await _get_visible_sellers(PROVINCE_ID, REMOTE_MUNICIPALITY_ID)
        local_ids, delivery_ids = _split_sellers_by_locality(
            seller_by_id,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        query = _build_marketplace_products_query(local_ids, delivery_ids)
        products = get_catalog_products_collection()
        self.assertEqual(
            await products.count_documents({**query, "_id": self.seed.view_only_id}),
            0,
        )

    async def test_marketplace_shows_delivery_product_for_remote(self) -> None:
        seller_by_id = await _get_visible_sellers(PROVINCE_ID, REMOTE_MUNICIPALITY_ID)
        local_ids, delivery_ids = _split_sellers_by_locality(
            seller_by_id,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        query = _build_marketplace_products_query(local_ids, delivery_ids)
        products = get_catalog_products_collection()
        self.assertEqual(
            await products.count_documents({**query, "_id": self.seed.with_delivery_id}),
            1,
        )

    async def test_catalog_total_matches_available_products(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        self.assertGreaterEqual(catalog.total_products, 4)

    async def test_view_only_flag_preserved_in_catalog(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        view_only = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.seed.view_only_id)
        )
        self.assertTrue(view_only.view_only)

    async def test_local_buyer_has_no_pickup_notice_on_pickup_product(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        pickup_product = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(self.seed.pickup_only_id)
        )
        self.assertFalse(pickup_product.pickup_required)

    async def test_empty_category_is_not_returned(self) -> None:
        categories = get_catalog_categories_collection()
        empty_category_id = ObjectId()
        await categories.insert_one(
            category_document(
                seller_id=self.seed.seller_id,
                category_id=empty_category_id,
                name="Vacía",
                sort_order=99,
            )
        )
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
        )
        section_ids = {section.category_id for section in catalog.sections}
        self.assertNotIn(str(empty_category_id), section_ids)

    async def test_pagination_has_more_when_limit_is_small(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            REMOTE_MUNICIPALITY_ID,
            limit_per_category=1,
        )
        self.assertTrue(any(section.has_more for section in catalog.sections))


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class StoreCatalogApiIntegrationTests(unittest.TestCase):
    seed: StoreCatalogSeed

    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        async def prepare() -> StoreCatalogSeed:
            await connect_to_mongo()
            await cleanup_store_catalog_test_data()
            return await seed_store_catalog_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_store_catalog_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_http_catalog_remote_includes_pickup_only(self) -> None:
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
        product_ids = {
            product["id"]
            for section in response.json().get("sections", [])
            for product in section.get("products", [])
        }
        self.assertIn(str(self.seed.pickup_only_id), product_ids)
        self.assertIn(str(self.seed.unavailable_id), product_ids)
        unavailable = next(
            product
            for section in response.json().get("sections", [])
            for product in section.get("products", [])
            if product["id"] == str(self.seed.unavailable_id)
        )
        self.assertFalse(unavailable["is_available"])

    def test_http_catalog_pickup_only_store_not_empty(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                f"/api/marketplace/stores/{STORE_SLUG_PICKUP_ONLY}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": REMOTE_MUNICIPALITY_ID,
                    "limit_per_category": 20,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreater(payload.get("total_products", 0), 0)

    def test_http_category_products_remote_includes_pickup_only(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                f"/api/marketplace/stores/{STORE_SLUG}/categories/{self.seed.category_id}/products",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": REMOTE_MUNICIPALITY_ID,
                    "limit": 20,
                    "offset": 0,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        product_ids = {product["id"] for product in response.json().get("products", [])}
        self.assertIn(str(self.seed.pickup_only_id), product_ids)

    def test_http_catalog_no_categories_fallback(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                f"/api/marketplace/stores/{STORE_SLUG_NO_CATEGORIES}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": REMOTE_MUNICIPALITY_ID,
                    "limit_per_category": 20,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        sections = response.json().get("sections", [])
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["category_name"], "Catálogo")

    def test_http_catalog_orphan_category_section(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                f"/api/marketplace/stores/{STORE_SLUG_ORPHAN}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": REMOTE_MUNICIPALITY_ID,
                    "limit_per_category": 20,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        section_names = {
            section["category_name"]
            for section in response.json().get("sections", [])
        }
        self.assertIn("Otros", section_names)


if __name__ == "__main__":
    unittest.main()
