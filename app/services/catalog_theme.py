from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

CatalogTheme = Literal[
    "default",
    "grey",
    "red",
    "pink",
    "green",
    "blue",
    "purple",
    "orange",
    "yellow",
    "carmelita",
]
DEFAULT_CATALOG_THEME: CatalogTheme = "default"

CATALOG_THEMES: tuple[CatalogTheme, ...] = (
    "default",
    "grey",
    "red",
    "pink",
    "green",
    "blue",
    "purple",
    "orange",
    "yellow",
    "carmelita",
)

PALETTE_SLOTS: tuple[str, ...] = ("primary", "background", "accent", "secondary")

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

# Tokens semánticos alineados con index.css (.catalog-theme-scope.*)
THEME_TOKENS: dict[str, dict[str, str]] = {
    "default": {
        "primary": "#59802c",
        "background": "#fdfbf2",
        "accent": "#f5c71a",
        "secondary": "#7b4c38",
    },
    "grey": {
        "primary": "#2b2b2b",
        "background": "#e0e0e0",
        "accent": "#b3b3b3",
        "secondary": "#848484",
    },
    "red": {
        "primary": "#cc0000",
        "background": "#fdfbf2",
        "accent": "#ff5722",
        "secondary": "#e60000",
    },
    "pink": {
        "primary": "#c2185b",
        "background": "#fce4ec",
        "accent": "#f48fb1",
        "secondary": "#e91e63",
    },
    "green": {
        "primary": "#33691e",
        "background": "#f1f8e9",
        "accent": "#9acd32",
        "secondary": "#558b2f",
    },
    "blue": {
        "primary": "#092c56",
        "background": "#f0f5f4",
        "accent": "#2196f3",
        "secondary": "#225688",
    },
    "purple": {
        "primary": "#312a44",
        "background": "#dad4df",
        "accent": "#8870e3",
        "secondary": "#5b4b8a",
    },
    "orange": {
        "primary": "#c24100",
        "background": "#fff8f0",
        "accent": "#ff7b00",
        "secondary": "#9a3412",
    },
    "yellow": {
        "primary": "#7a6200",
        "background": "#fdfbcf",
        "accent": "#f7c319",
        "secondary": "#8a6d00",
    },
    "carmelita": {
        "primary": "#5e3023",
        "background": "#f3e9dc",
        "accent": "#c08552",
        "secondary": "#895737",
    },
}


class PaletteColor(TypedDict):
    hex: str
    opacity: int


CatalogPalette = dict[str, PaletteColor]


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


def parse_hex_color(value: Any) -> str:
    raw = str(value or "").strip()
    match = _HEX_RE.fullmatch(raw)
    if not match:
        raise ValueError("El color debe ser un hex de 6 dígitos, por ejemplo #59802c.")
    return f"#{match.group(1).lower()}"


def parse_opacity(value: Any) -> int:
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError("La opacidad debe ser un número entre 0 y 100.") from exc
    return max(0, min(100, amount))


def palette_from_theme(theme: str | None) -> CatalogPalette:
    tokens = THEME_TOKENS[normalize_catalog_theme(theme)]
    return {
        slot: {"hex": tokens[slot], "opacity": 100}
        for slot in PALETTE_SLOTS
    }


def _parse_palette_slot(raw: Any, fallback: PaletteColor) -> PaletteColor:
    if not isinstance(raw, dict):
        return {"hex": fallback["hex"], "opacity": fallback["opacity"]}
    hex_value = fallback["hex"]
    if raw.get("hex") not in (None, ""):
        hex_value = parse_hex_color(raw.get("hex"))
    opacity = fallback["opacity"]
    if raw.get("opacity") is not None and raw.get("opacity") != "":
        opacity = parse_opacity(raw.get("opacity"))
    return {"hex": hex_value, "opacity": opacity}


def parse_catalog_palette(value: Any, theme: str | None = None) -> CatalogPalette:
    fallback = palette_from_theme(theme)
    if value is None:
        return fallback
    if not isinstance(value, dict):
        raise ValueError("La paleta de colores no es válida.")
    return {slot: _parse_palette_slot(value.get(slot), fallback[slot]) for slot in PALETTE_SLOTS}


def normalize_catalog_palette(value: Any, theme: str | None = None) -> CatalogPalette | None:
    if value is None or value == "":
        return None
    try:
        return parse_catalog_palette(value, theme)
    except ValueError:
        return None


def public_catalog_palette(value: Any, theme: str | None = None) -> CatalogPalette | None:
    parsed = normalize_catalog_palette(value, theme)
    if parsed is None:
        return palette_from_theme(theme)
    return parsed
