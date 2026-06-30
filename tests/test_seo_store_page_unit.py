from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.schemas.marketplace import (
    MarketplaceStoreCatalogPublic,
    MarketplaceStoreLocalSectionPublic,
    MarketplaceStorePublic,
)
from app.schemas.seller_profile import BusinessArea, CategoryPublic
from app.services import seo_store_page as seo_store_page_service


def _sample_catalog() -> MarketplaceStoreCatalogPublic:
    return MarketplaceStoreCatalogPublic(
        store=MarketplaceStorePublic(
            id="seller-1",
            store_name="Panadería La Habana",
            store_slug="panaderia-la-habana",
            phone="+53 5 1234567",
            profile_photo_url="https://example.com/store.jpg",
        ),
        biography="Pan fresquito cada mañana.",
        business_area=BusinessArea(
            province_id="la-habana",
            province_name="La Habana",
            municipality_id="playa",
            municipality_name="Playa",
        ),
        categories=[CategoryPublic(id="food", name="Comida y bebidas")],
        sections=[
            MarketplaceStoreLocalSectionPublic(
                category_id="cat-1",
                category_name="Panadería",
                products=[],
                total_products=1,
                has_more=False,
            )
        ],
        total_products=1,
    )


class SeoStorePageTests(unittest.TestCase):
    def test_build_store_page_title(self) -> None:
        title = seo_store_page_service.build_store_page_title(_sample_catalog())
        self.assertEqual(title, "Panadería La Habana | Catálogo en Pa' La Jaba")

    def test_build_store_meta_description_uses_biography(self) -> None:
        description = seo_store_page_service.build_store_meta_description(_sample_catalog())
        self.assertIn("Pan fresquito", description)

    def test_build_store_body_html_escapes_content(self) -> None:
        catalog = _sample_catalog()
        catalog.store.store_name = "Cafe & Bar <Test>"
        html = seo_store_page_service.build_store_body_html(catalog)
        self.assertIn("Cafe &amp; Bar &lt;Test&gt;", html)
        self.assertIn("<h1>", html)

    def test_build_store_head_html_includes_canonical_and_json_ld(self) -> None:
        head = seo_store_page_service.build_store_head_html(
            _sample_catalog(),
            site_url="https://palajaba.com",
        )
        self.assertIn('rel="canonical"', head)
        self.assertIn("https://palajaba.com/panaderia-la-habana", head)
        self.assertIn('"@type": "Store"', head)
        self.assertIn("Panadería La Habana", head)


class SeoStorePageAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_store_page_document_includes_body_and_root(self) -> None:
        with patch(
            "app.services.seo_store_page.load_seo_store_catalog",
            new=AsyncMock(return_value=_sample_catalog()),
        ):
            html = await seo_store_page_service.build_store_page_document(
                "panaderia-la-habana",
                site_url="https://palajaba.com",
                asset_tags='<script type="module" src="/assets/index.js"></script>',
            )

        self.assertIn("<article class=\"seo-store-page\">", html)
        self.assertIn('<div id="root">', html)
        self.assertIn("/assets/index.js", html)
        self.assertIn("Panadería La Habana", html)


if __name__ == "__main__":
    unittest.main()
