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
from app.services.catalog_theme_settings import get_seller_catalog_theme
from app.services.marketplace import get_store_catalog
from tests.helpers import PROVINCE_ID, SELLER_MUNICIPALITY_ID
from tests.helpers_catalog_product_sort import (
    MARKER,
    STORE_NAME,
    STORE_SLUG,
    category_document,
    product_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


class CatalogThemeSeed:
    seller_id: str
    category_id: ObjectId


async def cleanup_catalog_theme_test_data() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()
    await products.delete_many({"catalog_product_sort_test_marker": MARKER})
    await categories.delete_many({"catalog_product_sort_test_marker": MARKER})
    await registrations.delete_many({"catalog_product_sort_test_marker": MARKER})


async def seed_catalog_theme_test_data() -> CatalogThemeSeed:
    seed = CatalogThemeSeed()
    seller_oid = ObjectId()
    seed.seller_id = str(seller_oid)
    seed.category_id = ObjectId()

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
    await products.insert_one(
        product_document(
            seller_id=seed.seller_id,
            category_id=seed.category_id,
            name="Producto tema",
            base_price=100.0,
        )
    )
    await categories.update_one(
        {"_id": seed.category_id},
        {"$set": {"product_count": 1}},
    )
    return seed


def seller_auth_header(seller_id: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=STORE_NAME)
    return {"Authorization": f"Bearer {token}"}


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CatalogThemeServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    seed: CatalogThemeSeed

    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_catalog_theme_test_data()
        self.seed = await seed_catalog_theme_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_catalog_theme_test_data()
        await close_mongo_connection()

    async def test_legacy_seller_defaults_to_default_theme(self) -> None:
        theme = await get_seller_catalog_theme(self.seed.seller_id)
        self.assertEqual(theme, "default")

    async def test_startup_backfills_missing_catalog_theme_field(self) -> None:
        from app.services.catalog_theme_settings import ensure_catalog_theme_defaults_on_startup

        registrations = get_registrations_collection()
        seller_oid = ObjectId(self.seed.seller_id)
        await registrations.update_one(
            {"_id": seller_oid},
            {"$unset": {"catalog_theme": ""}},
        )
        doc = await registrations.find_one({"_id": seller_oid})
        self.assertNotIn("catalog_theme", doc or {})

        updated = await ensure_catalog_theme_defaults_on_startup()
        self.assertGreaterEqual(updated, 1)

        doc = await registrations.find_one({"_id": seller_oid})
        self.assertEqual(doc.get("catalog_theme"), "default")

    async def test_startup_does_not_overwrite_existing_catalog_theme(self) -> None:
        from app.services.catalog_theme_settings import ensure_catalog_theme_defaults_on_startup

        registrations = get_registrations_collection()
        seller_oid = ObjectId(self.seed.seller_id)
        await registrations.update_one(
            {"_id": seller_oid},
            {"$set": {"catalog_theme": "grey"}},
        )

        await ensure_catalog_theme_defaults_on_startup()

        doc = await registrations.find_one({"_id": seller_oid})
        self.assertEqual(doc.get("catalog_theme"), "grey")

    async def test_store_catalog_exposes_default_theme_for_legacy_seller(self) -> None:
        catalog = await get_store_catalog(
            STORE_SLUG,
            PROVINCE_ID,
            SELLER_MUNICIPALITY_ID,
        )
        self.assertEqual(catalog.catalog_theme, "default")


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CatalogThemeApiIntegrationTests(unittest.TestCase):
    seed: CatalogThemeSeed

    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        async def prepare() -> CatalogThemeSeed:
            await connect_to_mongo()
            await cleanup_catalog_theme_test_data()
            return await seed_catalog_theme_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_catalog_theme_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_patch_catalog_theme_persists_blue(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=seller_auth_header(self.seed.seller_id),
                json={"catalog_theme": "blue"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["catalog_theme"], "blue")

    def test_patch_catalog_theme_persists_green(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=seller_auth_header(self.seed.seller_id),
                json={"catalog_theme": "green"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["catalog_theme"], "green")

    def test_patch_catalog_theme_persists_pink(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=seller_auth_header(self.seed.seller_id),
                json={"catalog_theme": "pink"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["catalog_theme"], "pink")

    def test_patch_catalog_theme_persists_red(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=seller_auth_header(self.seed.seller_id),
                json={"catalog_theme": "red"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["catalog_theme"], "red")

    def test_patch_catalog_theme_persists_grey(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=seller_auth_header(self.seed.seller_id),
                json={"catalog_theme": "grey"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["catalog_theme"], "grey")

    def test_store_catalog_returns_persisted_theme(self) -> None:
        import asyncio

        async def fetch_theme() -> str:
            await connect_to_mongo()
            catalog = await get_store_catalog(
                STORE_SLUG,
                PROVINCE_ID,
                SELLER_MUNICIPALITY_ID,
            )
            await close_mongo_connection()
            return catalog.catalog_theme

        self.assertEqual(asyncio.run(fetch_theme()), "red")

    def test_patch_rejects_unknown_theme(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=seller_auth_header(self.seed.seller_id),
                json={"catalog_theme": "neon"},
            )
        self.assertEqual(response.status_code, 422, response.text)
