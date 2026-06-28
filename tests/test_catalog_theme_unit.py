from __future__ import annotations

import unittest

from app.services.catalog_theme import (
    CATALOG_THEMES,
    DEFAULT_CATALOG_THEME,
    normalize_catalog_theme,
    parse_catalog_theme,
)


class NormalizeCatalogThemeTests(unittest.TestCase):
    def test_defaults_to_platform_theme_when_missing(self) -> None:
        self.assertEqual(normalize_catalog_theme(None), "default")
        self.assertEqual(normalize_catalog_theme(""), "default")
        self.assertEqual(normalize_catalog_theme("unknown"), "default")

    def test_accepts_supported_themes(self) -> None:
        for theme in CATALOG_THEMES:
            self.assertEqual(normalize_catalog_theme(theme), theme)

    def test_normalizes_case_and_whitespace(self) -> None:
        self.assertEqual(normalize_catalog_theme(" GREY "), "grey")
        self.assertEqual(parse_catalog_theme(" GREY "), "grey")
        self.assertEqual(normalize_catalog_theme(" RED "), "red")
        self.assertEqual(parse_catalog_theme(" RED "), "red")
        self.assertEqual(normalize_catalog_theme(" PINK "), "pink")
        self.assertEqual(parse_catalog_theme(" PINK "), "pink")
        self.assertEqual(normalize_catalog_theme(" GREEN "), "green")
        self.assertEqual(parse_catalog_theme(" GREEN "), "green")

    def test_parse_rejects_unknown_theme(self) -> None:
        with self.assertRaises(ValueError):
            parse_catalog_theme("neon")

    def test_default_constant_is_default(self) -> None:
        self.assertEqual(DEFAULT_CATALOG_THEME, "default")
