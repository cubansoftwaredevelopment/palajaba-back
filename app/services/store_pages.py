import json
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status

STORE_PAGE_KEYS = ("faq", "about", "delivery_policy", "terms")
STORE_PAGE_SLUGS = {
    "faq": "faq",
    "sobre-nosotros": "about",
    "politica-de-entrega": "delivery_policy",
    "terminos-y-condiciones": "terms",
}
STORE_PAGE_TITLES = {
    "faq": "FAQ",
    "about": "Sobre nosotros",
    "delivery_policy": "Política de entrega",
    "terms": "Términos y condiciones",
}

_NODE_TYPES = frozenset(
    {
        "doc",
        "paragraph",
        "text",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "blockquote",
        "hardBreak",
        "image",
    }
)
_PLAIN_MARKS = frozenset({"bold", "italic", "strike", "underline"})
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_COLOR = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([01](?:\.0+)?|0?\.\d+)\s*)?\)$",
    re.IGNORECASE,
)
_ALIGNMENTS = frozenset({"left", "center", "right"})
_CONTAINER_TYPES = frozenset(
    {"doc", "paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote"}
)
_MAX_BYTES = 50_000
_MIN_WIDTH = 5
_MAX_WIDTH = 100

_INVALID_CONTENT = "El contenido de la página no es válido."
_INVALID_IMAGE = "La imagen de la página no es válida."
_INVALID_WIDTH = "El tamaño de la imagen no es válido."
_TOO_LARGE = "La página excede el tamaño permitido."


def _reject(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _clean_width(value: Any) -> int:
    if value is None:
        return 100
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject(_INVALID_WIDTH)
    if isinstance(value, float) and not value.is_integer():
        _reject(_INVALID_WIDTH)
    width = int(value)
    if width < _MIN_WIDTH or width > _MAX_WIDTH:
        _reject(_INVALID_WIDTH)
    return width


def _assert_image_src(src: str) -> None:
    if src.startswith("/uploads/store-pages/") and ".." not in src and "\\" not in src:
        return
    parsed = urlparse(src)
    if parsed.scheme == "https" and parsed.hostname == "res.cloudinary.com":
        return
    _reject(_INVALID_IMAGE)


def _color_channel(value: str) -> int:
    number = int(value)
    if number > 255:
        _reject(_INVALID_CONTENT)
    return number


def _normalize_color(value: Any) -> str:
    if not isinstance(value, str):
        _reject(_INVALID_CONTENT)
    color = value.strip()
    if _HEX_COLOR.fullmatch(color):
        if len(color) == 4:
            color = "#" + "".join(character * 2 for character in color[1:])
        return color.lower()
    match = _RGB_COLOR.fullmatch(color)
    if not match:
        _reject(_INVALID_CONTENT)
    alpha = match.group(4)
    if alpha is not None and float(alpha) != 1:
        _reject(_INVALID_CONTENT)
    red = _color_channel(match.group(1))
    green = _color_channel(match.group(2))
    blue = _color_channel(match.group(3))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _clean_href(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        _reject(_INVALID_CONTENT)
    href = value.strip()
    if not href:
        return None
    if len(href) > 2000 or any(ord(char) < 32 or char in '<>"\'\\' for char in href):
        _reject(_INVALID_CONTENT)
    if href.startswith("/") and not href.startswith("//"):
        return href
    parsed = urlparse(href)
    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        return href
    _reject(_INVALID_CONTENT)


def _text_align(attrs: dict[str, Any]) -> str | None:
    if "textAlign" not in attrs:
        return None
    value = attrs.get("textAlign")
    if value is None or value == "" or value == "left":
        return None
    if not isinstance(value, str) or value not in _ALIGNMENTS:
        _reject(_INVALID_CONTENT)
    return value


def _clean_mark(mark: Any) -> dict[str, Any] | None:
    if not isinstance(mark, dict):
        _reject(_INVALID_CONTENT)
    mark_type = mark.get("type")
    if mark_type in _PLAIN_MARKS:
        return {"type": mark_type}
    if mark_type == "link":
        attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
        href = _clean_href(attrs.get("href"))
        if not href:
            return None
        return {"type": "link", "attrs": {"href": href}}
    if mark_type != "textStyle":
        _reject(_INVALID_CONTENT)
    attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
    color = attrs.get("color")
    if color is None or color == "":
        return None
    return {"type": "textStyle", "attrs": {"color": _normalize_color(color)}}


def _clean_node(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        _reject(_INVALID_CONTENT)
    node_type = node.get("type")
    if node_type not in _NODE_TYPES:
        _reject(_INVALID_CONTENT)
    if node_type in {"text", "image", "hardBreak"} and node.get("content"):
        _reject(_INVALID_CONTENT)

    cleaned: dict[str, Any] = {"type": node_type}

    if node_type == "text":
        text = node.get("text")
        if not isinstance(text, str):
            _reject(_INVALID_CONTENT)
        cleaned["text"] = text
        marks = node.get("marks") or []
        if marks:
            if not isinstance(marks, list):
                _reject(_INVALID_CONTENT)
            cleaned_marks = []
            for mark in marks:
                cleaned_mark = _clean_mark(mark)
                if cleaned_mark:
                    cleaned_marks.append(cleaned_mark)
            if cleaned_marks:
                cleaned["marks"] = cleaned_marks
        return cleaned

    if node_type == "hardBreak":
        return cleaned

    if node_type == "image":
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        src = str(attrs.get("src") or "")
        _assert_image_src(src)
        image_attrs: dict[str, Any] = {"src": src, "width": _clean_width(attrs.get("width"))}
        alt = attrs.get("alt")
        if isinstance(alt, str) and alt.strip():
            image_attrs["alt"] = alt.strip()[:200]
        align = _text_align(attrs)
        if align:
            image_attrs["textAlign"] = align
        if "href" in attrs:
            href = _clean_href(attrs.get("href"))
            if href:
                image_attrs["href"] = href
        cleaned["attrs"] = image_attrs
        return cleaned

    if node_type == "heading":
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        level = attrs.get("level", 2)
        if isinstance(level, bool) or not isinstance(level, int) or level < 1 or level > 4:
            _reject(_INVALID_CONTENT)
        cleaned["attrs"] = {"level": level}
        align = _text_align(attrs)
        if align:
            cleaned["attrs"]["textAlign"] = align

    if node_type == "paragraph":
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        align = _text_align(attrs)
        if align:
            cleaned["attrs"] = {"textAlign": align}

    children = node.get("content") or []
    if not isinstance(children, list):
        _reject(_INVALID_CONTENT)
    if children or node_type in _CONTAINER_TYPES:
        cleaned["content"] = [_clean_node(child) for child in children]
    return cleaned


def sanitize_store_page_content(content: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, dict) or content.get("type") != "doc":
        _reject(_INVALID_CONTENT)
    try:
        encoded = json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_TOO_LARGE) from exc
    if len(encoded) > _MAX_BYTES:
        _reject(_TOO_LARGE)
    return _clean_node(content)


def store_page_has_content(content: Any) -> bool:
    found = False

    def walk(node: Any) -> None:
        nonlocal found
        if found or not isinstance(node, dict):
            return
        if node.get("type") == "text" and str(node.get("text") or "").strip():
            found = True
            return
        if node.get("type") == "image" and str((node.get("attrs") or {}).get("src") or "").strip():
            found = True
            return
        for child in node.get("content") or []:
            walk(child)

    walk(content)
    return found


def store_pages_from_document(doc: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    raw = doc.get("store_pages")
    if not isinstance(raw, dict):
        raw = {}
    pages: dict[str, dict[str, Any] | None] = {}
    for key in STORE_PAGE_KEYS:
        value = raw.get(key)
        pages[key] = value if isinstance(value, dict) and value.get("type") == "doc" else None
    return pages


def store_page_flags(doc: dict[str, Any]) -> dict[str, bool]:
    raw = doc.get("store_pages")
    if not isinstance(raw, dict):
        raw = {}
    return {key: store_page_has_content(raw.get(key)) for key in STORE_PAGE_KEYS}
