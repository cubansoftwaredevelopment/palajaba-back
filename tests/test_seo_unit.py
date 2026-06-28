from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.services import seo as seo_service
from app.utils.reserved_store_slugs import is_reserved_store_slug


class SeoSitemapTests(unittest.TestCase):
    def test_build_sitemap_xml_includes_static_and_store_urls(self) -> None:
        xml = seo_service.build_sitemap_xml(
            "https://palajaba.com",
            [{"slug": "panaderia-la-habana", "lastmod": "2026-06-01"}],
        )

        self.assertIn("<loc>https://palajaba.com</loc>", xml)
        self.assertIn("<loc>https://palajaba.com/comprar</loc>", xml)
        self.assertIn("<loc>https://palajaba.com/panaderia-la-habana</loc>", xml)
        self.assertIn("<lastmod>2026-06-01</lastmod>", xml)

    def test_build_sitemap_xml_escapes_special_characters(self) -> None:
        xml = seo_service.build_sitemap_xml(
            "https://palajaba.com",
            [{"slug": "cafe&bar", "lastmod": None}],
        )

        self.assertIn("<loc>https://palajaba.com/cafe&amp;bar</loc>", xml)

    def test_reserved_store_slug_blocks_indexing(self) -> None:
        self.assertTrue(is_reserved_store_slug("admin"))
        self.assertTrue(is_reserved_store_slug("comprar"))
        self.assertFalse(is_reserved_store_slug("mi-tienda"))


class SeoStoreListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_indexable_store_entries_filters_incomplete_and_reserved(self) -> None:
        docs = [
            {
                "status": "approved",
                "store_slug": "admin",
                "store_name": "Admin Shop",
                "updated_at": datetime(2026, 6, 1),
                "profile_photo_url": "https://example.com/a.jpg",
                "category_ids": ["food"],
                "offers_delivery": True,
                "business_area": {
                    "province_id": "la-habana",
                    "province_name": "La Habana",
                    "municipality_id": "playa",
                    "municipality_name": "Playa",
                },
                "subscription_starts_at": datetime(2026, 5, 1),
                "subscription_ends_at": datetime(2027, 5, 1),
            },
            {
                "status": "approved",
                "store_slug": "tienda-valida",
                "store_name": "Tienda Valida",
                "updated_at": datetime(2026, 6, 2),
                "profile_photo_url": "https://example.com/b.jpg",
                "category_ids": ["food"],
                "offers_delivery": False,
                "business_area": {
                    "province_id": "la-habana",
                    "province_name": "La Habana",
                    "municipality_id": "playa",
                    "municipality_name": "Playa",
                },
                "subscription_starts_at": datetime(2026, 5, 1),
                "subscription_ends_at": datetime(2027, 5, 1),
            },
            {
                "status": "approved",
                "store_slug": "sin-perfil",
                "store_name": "Sin Perfil",
                "updated_at": datetime(2026, 6, 3),
                "category_ids": ["food"],
                "offers_delivery": True,
                "subscription_starts_at": datetime(2026, 5, 1),
                "subscription_ends_at": datetime(2027, 5, 1),
            },
        ]

        class FakeCursor:
            def __init__(self, items):
                self._items = items

            def __aiter__(self):
                async def generator():
                    for item in self._items:
                        yield item

                return generator()

        fake_collection = MagicMock()
        fake_collection.find.return_value = FakeCursor(docs)

        with patch("app.services.seo.get_registrations_collection", return_value=fake_collection):
            entries = await seo_service.list_indexable_store_entries()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["slug"], "tienda-valida")
        self.assertEqual(entries[0]["lastmod"], "2026-06-02")


if __name__ == "__main__":
    unittest.main()
