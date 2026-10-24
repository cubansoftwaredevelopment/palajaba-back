"""Recorrido de tema y paleta: API del vendedor, catálogo público y Mongo."""

from __future__ import annotations

import unittest

from app.services.catalog_theme import palette_from_theme
from app.subscriptions.service import CATALOG_THEME_PLAN_REQUIRED_MESSAGE
from test_e2e.catalog_theme.utils.fixtures import (
    cleanup_db,
    headers_for,
    load_seller,
    seed_seller,
    theme_update_payload,
)
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class CatalogThemeE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_premium_seller_saves_normalized_palette_and_public_catalog_reads_it(self) -> None:
        seller = seed_seller("premium")
        payload = theme_update_payload(theme="red", primary_hex="FF0000", primary_opacity=50)

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/catalog/theme",
                headers=headers_for(seller),
                json=payload,
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            body = saved.json()
            self.assertEqual(body["catalog_theme"], "red")
            self.assertEqual(body["catalog_palette"]["primary"], {"hex": "#ff0000", "opacity": 50})
            self.assertEqual(
                body["catalog_palette"]["background"],
                palette_from_theme("red")["background"],
            )

            me = client.get("/api/auth/me", headers=headers_for(seller))
            self.assertEqual(me.status_code, 200, me.text)
            self.assertEqual(me.json()["catalog_theme"], "red")
            self.assertEqual(me.json()["catalog_palette"]["primary"]["hex"], "#ff0000")

            public = client.get(
                f"/api/marketplace/stores/{seller['store_slug']}/catalog",
                params={
                    "province_id": PROVINCE_ID,
                    "municipality_id": SELLER_MUNICIPALITY_ID,
                },
            )
            self.assertEqual(public.status_code, 200, public.text)
            catalog = public.json()
            self.assertEqual(catalog["catalog_theme"], "red")
            self.assertEqual(catalog["catalog_palette"]["primary"], {"hex": "#ff0000", "opacity": 50})

        stored = load_seller(seller["seller_id"])
        self.assertEqual(stored["catalog_theme"], "red")
        self.assertEqual(stored["catalog_palette"]["primary"], {"hex": "#ff0000", "opacity": 50})

    def test_standard_seller_cannot_customize_catalog_theme(self) -> None:
        seller = seed_seller("standard")
        payload = theme_update_payload(theme="blue", primary_hex="#2196f3", primary_opacity=100)

        with api_client() as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=headers_for(seller),
                json=payload,
            )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], CATALOG_THEME_PLAN_REQUIRED_MESSAGE)
        stored = load_seller(seller["seller_id"])
        self.assertEqual(stored.get("catalog_theme"), "default")

    def test_invalid_hex_is_rejected_before_saving(self) -> None:
        seller = seed_seller("premium")
        payload = theme_update_payload(theme="default", primary_hex="not-a-color", primary_opacity=40)

        with api_client() as client:
            response = client.patch(
                "/api/auth/me/catalog/theme",
                headers=headers_for(seller),
                json=payload,
            )

        self.assertEqual(response.status_code, 422, response.text)
        stored = load_seller(seller["seller_id"])
        self.assertNotIn("catalog_palette", stored)
