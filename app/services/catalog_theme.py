from typing import Literal

CatalogTheme = Literal["default", "grey", "red", "pink", "green", "blue"]
DEFAULT_CATALOG_THEME: CatalogTheme = "default"

CATALOG_THEMES: tuple[CatalogTheme, ...] = ("default", "grey", "red", "pink", "green", "blue")


def _coerce_catalog_theme(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def parse_catalog_theme(value: str) -> CatalogTheme:
    theme = _coerce_catalog_theme(value)
    if theme not in CATALOG_THEMES:
        options = ", ".join(CATALOG_THEMES)
        raise ValueError(f"Tema no válido. Opciones: {options}")
    return theme  # type: ignore[return-value]


def normalize_catalog_theme(value: str | None) -> CatalogTheme:
    theme = _coerce_catalog_theme(value)
    if theme in CATALOG_THEMES:
        return theme  # type: ignore[return-value]
    return DEFAULT_CATALOG_THEME
