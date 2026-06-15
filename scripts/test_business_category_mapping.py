"""
Tests del mapeo de categorías globales de producto → categorías de negocio.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_business_category_mapping.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.categories import (
    business_category_name,
    business_category_source_ids,
    normalize_business_category_id,
)
from app.services.marketplace import _display_category_name


class BusinessCategoryMappingTests(unittest.TestCase):
    def test_construccion_id_uses_business_name(self) -> None:
        self.assertEqual(normalize_business_category_id("construccion"), "construccion")
        self.assertEqual(
            business_category_name("construccion"),
            "Materiales y herramientas de construcción",
        )
        self.assertEqual(
            _display_category_name("construccion"),
            "Materiales y herramientas de construcción",
        )

    def test_legacy_revolico_id_maps_to_construccion(self) -> None:
        self.assertEqual(normalize_business_category_id("construccion-herramientas"), "construccion")
        self.assertEqual(
            _display_category_name("construccion-herramientas"),
            "Materiales y herramientas de construcción",
        )

    def test_legacy_ferreteria_id_maps_to_construccion(self) -> None:
        self.assertEqual(normalize_business_category_id("ferreteria"), "construccion")

    def test_artesanias_keeps_business_name(self) -> None:
        self.assertEqual(business_category_name("artesanias"), "Artesanías")
        self.assertEqual(_display_category_name("arte-antiguedades"), "Artesanías")

    def test_source_ids_include_aliases(self) -> None:
        source_ids = business_category_source_ids("construccion")
        self.assertIn("construccion", source_ids)
        self.assertIn("construccion-herramientas", source_ids)
        self.assertIn("ferreteria", source_ids)


if __name__ == "__main__":
    unittest.main()
