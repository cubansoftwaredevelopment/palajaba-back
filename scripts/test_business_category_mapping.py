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
    DEFAULT_CATEGORIES,
    business_category_name,
    business_category_sort_order,
    business_category_source_ids,
    categories_for_profile,
    normalize_business_category_id,
    resolve_product_global_category_id,
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

    def test_product_keeps_one_store_category_from_profile(self) -> None:
        allowed = ["comida", "restaurant", "construccion"]
        self.assertEqual(resolve_product_global_category_id(allowed, "restaurant"), "restaurant")
        self.assertEqual(resolve_product_global_category_id(allowed, "comida"), "comida")
        self.assertEqual(resolve_product_global_category_id(allowed, "construccion"), "construccion")

    def test_product_rejects_category_not_in_store(self) -> None:
        with self.assertRaises(ValueError):
            resolve_product_global_category_id(["comida", "restaurant"], "moda")

    def test_medios_transporte_is_registered_category(self) -> None:
        ids = {item["id"] for item in DEFAULT_CATEGORIES}
        self.assertIn("medios-transporte", ids)
        self.assertEqual(business_category_name("medios-transporte"), "Medios de transporte")
        self.assertEqual(
            _display_category_name("medios-transporte"),
            "Medios de transporte",
        )

    def test_legacy_vehiculos_maps_to_medios_transporte(self) -> None:
        self.assertEqual(normalize_business_category_id("vehiculos-repuestos"), "medios-transporte")
        self.assertEqual(normalize_business_category_id("transporte"), "medios-transporte")
        self.assertEqual(
            _display_category_name("vehiculos-repuestos"),
            "Medios de transporte",
        )

    def test_medios_transporte_source_ids_include_aliases(self) -> None:
        source_ids = business_category_source_ids("medios-transporte")
        self.assertIn("medios-transporte", source_ids)
        self.assertIn("vehiculos-repuestos", source_ids)
        self.assertIn("transporte", source_ids)

    def test_product_accepts_medios_transporte_for_transport_store(self) -> None:
        allowed = ["medios-transporte", "servicios"]
        self.assertEqual(
            resolve_product_global_category_id(allowed, "medios-transporte"),
            "medios-transporte",
        )
        self.assertEqual(
            resolve_product_global_category_id(allowed, "vehiculos-repuestos"),
            "medios-transporte",
        )

    def test_categories_for_profile_preserves_medios_transporte_id(self) -> None:
        result = categories_for_profile(["medios-transporte"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "medios-transporte")
        self.assertEqual(result[0].name, "Medios de transporte")

    def test_medios_transporte_sort_order_before_servicios(self) -> None:
        self.assertLess(
            business_category_sort_order("medios-transporte"),
            business_category_sort_order("servicios"),
        )

    def test_articulos_limpieza_is_registered_category(self) -> None:
        ids = {item["id"] for item in DEFAULT_CATEGORIES}
        self.assertIn("articulos-limpieza", ids)
        self.assertEqual(business_category_name("articulos-limpieza"), "Articulos de limpieza")
        self.assertEqual(
            _display_category_name("articulos-limpieza"),
            "Articulos de limpieza",
        )

    def test_suplementos_gimnasio_is_registered_category(self) -> None:
        ids = {item["id"] for item in DEFAULT_CATEGORIES}
        self.assertIn("suplementos-gimnasio", ids)
        self.assertEqual(
            business_category_name("suplementos-gimnasio"),
            "Suplementos y articulos de gimnasio",
        )
        self.assertEqual(
            _display_category_name("suplementos-gimnasio"),
            "Suplementos y articulos de gimnasio",
        )

    def test_product_accepts_new_categories_for_matching_store(self) -> None:
        allowed = ["articulos-limpieza", "hogar"]
        self.assertEqual(
            resolve_product_global_category_id(allowed, "articulos-limpieza"),
            "articulos-limpieza",
        )
        allowed_gym = ["suplementos-gimnasio", "salud"]
        self.assertEqual(
            resolve_product_global_category_id(allowed_gym, "suplementos-gimnasio"),
            "suplementos-gimnasio",
        )

    def test_categories_for_profile_includes_new_globals(self) -> None:
        result = categories_for_profile(["articulos-limpieza", "suplementos-gimnasio"])
        self.assertEqual(
            [(item.id, item.name) for item in result],
            [
                ("articulos-limpieza", "Articulos de limpieza"),
                ("suplementos-gimnasio", "Suplementos y articulos de gimnasio"),
            ],
        )

    def test_new_categories_sort_before_otros(self) -> None:
        self.assertLess(
            business_category_sort_order("articulos-limpieza"),
            business_category_sort_order("otros"),
        )
        self.assertLess(
            business_category_sort_order("suplementos-gimnasio"),
            business_category_sort_order("otros"),
        )


if __name__ == "__main__":
    unittest.main()
