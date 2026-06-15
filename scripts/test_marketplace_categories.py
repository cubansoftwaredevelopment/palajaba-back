"""
Tests del mapeo categoría de negocio → categoría del marketplace.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_marketplace_categories.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.marketplace import _display_category_name, _normalize_marketplace_category_id
from app.services.product_categories import (
    marketplace_category_source_ids,
    resolve_marketplace_category_id,
)


class MarketplaceCategoryMappingTests(unittest.TestCase):
    def test_construccion_maps_to_construccion_herramientas(self) -> None:
        self.assertEqual(resolve_marketplace_category_id("construccion"), "construccion-herramientas")

    def test_construccion_display_name(self) -> None:
        self.assertEqual(_display_category_name("construccion"), "Construcción y Herramientas")

    def test_normalize_business_category_returns_product_id(self) -> None:
        self.assertEqual(_normalize_marketplace_category_id("construccion"), "construccion-herramientas")

    def test_source_ids_include_business_and_product(self) -> None:
        source_ids = marketplace_category_source_ids("construccion-herramientas")
        self.assertIn("construccion", source_ids)
        self.assertIn("construccion-herramientas", source_ids)

    def test_unknown_business_category_falls_back_to_otros(self) -> None:
        self.assertEqual(resolve_marketplace_category_id("categoria-inventada"), "otros")


if __name__ == "__main__":
    unittest.main()
