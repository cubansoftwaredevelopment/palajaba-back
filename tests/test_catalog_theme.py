from app.services.catalog_theme import (
    palette_from_theme,
    parse_catalog_palette,
    parse_hex_color,
    parse_opacity,
)


def test_parse_hex_color_normalizes():
    assert parse_hex_color("#59802C") == "#59802c"
    assert parse_hex_color("ff5722") == "#ff5722"


def test_parse_opacity_clamps():
    assert parse_opacity(40) == 40
    assert parse_opacity(-3) == 0
    assert parse_opacity(140) == 100


def test_parse_catalog_palette_fills_from_theme():
    palette = parse_catalog_palette({"primary": {"hex": "#ff0000", "opacity": 50}}, "default")
    assert palette["primary"] == {"hex": "#ff0000", "opacity": 50}
    assert palette["background"] == palette_from_theme("default")["background"]


if __name__ == "__main__":
    test_parse_hex_color_normalizes()
    test_parse_opacity_clamps()
    test_parse_catalog_palette_fills_from_theme()
    print("ok")
