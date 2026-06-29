from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import seo as seo_router
from app.schemas.marketplace import MarketplaceStoreCatalogPublic, MarketplaceStorePublic


def _sample_catalog() -> MarketplaceStoreCatalogPublic:
    return MarketplaceStoreCatalogPublic(
        store=MarketplaceStorePublic(
            id="seller-1",
            store_name="JStore",
            store_slug="jstore",
            phone="+53 5 1234567",
            profile_photo_url="https://example.com/store.jpg",
        ),
        total_products=0,
    )


class SeoStoreRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(seo_router.router)
        self.client = TestClient(app)

    def test_store_html_route_uses_slug_without_html_suffix(self) -> None:
        with patch(
            "app.routers.seo.seo_store_page_service.build_store_page_document",
            new=AsyncMock(return_value="<html><body>JStore</body></html>"),
        ) as build_document:
            response = self.client.get("/api/platform/seo/store/jstore.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        build_document.assert_awaited_once()
        self.assertEqual(build_document.await_args.args[0], "jstore")


if __name__ == "__main__":
    unittest.main()
