"""PDF separados de los términos y de la política de entrega aceptados en el pedido."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.utils.datetime import format_utc_naive_for_display

BRAND_GREEN_DARK = colors.HexColor("#3F5C1F")
TEXT_MUTED = colors.HexColor("#5C6B52")
RULE = colors.HexColor("#D8E4C8")

AGREEMENT_DOCUMENTS = {
    "terms": {
        "title": "Términos y condiciones",
        "empty": "Este pedido no tiene términos y condiciones registrados.",
        "filename": "terminos",
    },
    "delivery_policy": {
        "title": "Política de entrega",
        "empty": "Este pedido no tiene política de entrega registrada.",
        "filename": "politica-de-entrega",
    },
}


def _when(value: datetime | None) -> str:
    return format_utc_naive_for_display(value) if isinstance(value, datetime) else "—"


def _inline(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text") or "")
    if kind == "hardBreak":
        return "\n"
    if kind == "image":
        return "[Imagen]"
    return "".join(_inline(child) for child in node.get("content") or [])


def rich_doc_blocks(content: Any) -> list[tuple[str, str]]:
    """Convierte el documento de la tienda en bloques de texto para el PDF."""
    blocks: list[tuple[str, str]] = []

    def walk(node: Any, list_index: list[int] | None = None) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        children = node.get("content") or []
        if kind in {"doc", "blockquote"}:
            for child in children:
                walk(child)
            return
        if kind == "bulletList":
            for child in children:
                walk(child, [0])
            return
        if kind == "orderedList":
            number = 1
            for child in children:
                walk(child, [number])
                number += 1
            return
        if kind == "listItem":
            text = " ".join(_inline(child).split())
            if not text:
                return
            prefix = f"{list_index[0]}. " if list_index and list_index[0] else "• "
            blocks.append(("bullet", f"{prefix}{text}"))
            return
        if kind == "heading":
            text = " ".join(_inline(node).split())
            if text:
                blocks.append(("heading", text))
            return
        if kind == "paragraph":
            text = " ".join(_inline(node).split())
            if text:
                blocks.append(("paragraph", text))
            return
        for child in children:
            walk(child, list_index)

    walk(content)
    return blocks


class _Report:
    def __init__(self) -> None:
        self.buffer = BytesIO()
        self.pdf = canvas.Canvas(self.buffer, pagesize=A4, pageCompression=0)
        self.width, self.height = A4
        self.margin = 16 * mm
        self.bottom = 16 * mm
        self.y = self.height - self.margin
        self.content_width = self.width - (2 * self.margin)

    def ensure(self, needed: float) -> None:
        if self.y - needed >= self.bottom:
            return
        self.pdf.showPage()
        self.y = self.height - self.margin

    def gap(self, amount: float) -> None:
        self.ensure(amount)
        self.y -= amount

    def rule(self) -> None:
        self.ensure(4 * mm)
        self.pdf.setStrokeColor(RULE)
        self.pdf.setLineWidth(1)
        self.pdf.line(self.margin, self.y, self.width - self.margin, self.y)
        self.y -= 6 * mm

    def text(self, value: str, *, font: str = "Helvetica", size: int = 10, color=colors.black, leading: float = 13) -> None:
        self.pdf.setFont(font, size)
        words = str(value or "").split()
        if not words:
            return
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.pdf.stringWidth(candidate, font, size) <= self.content_width:
                line = candidate
                continue
            self._draw_line(line, font, size, color, leading)
            line = word
        if line:
            self._draw_line(line, font, size, color, leading)

    def _draw_line(self, line: str, font: str, size: int, color, leading: float) -> None:
        self.ensure(leading)
        self.pdf.setFillColor(color)
        self.pdf.setFont(font, size)
        self.pdf.drawString(self.margin, self.y - size, line)
        self.y -= leading

    def finish(self) -> bytes:
        self.pdf.save()
        return self.buffer.getvalue()


def _agreement(order: dict[str, Any], key: str) -> dict[str, Any] | None:
    raw = order.get("store_agreements")
    if not isinstance(raw, dict):
        return None
    value = raw.get(key)
    return value if isinstance(value, dict) else None


def _write_document(report: _Report, content: Any, empty: str) -> None:
    blocks = rich_doc_blocks(content)
    if not blocks:
        report.text(empty, color=TEXT_MUTED)
        return
    for kind, text in blocks:
        if kind == "heading":
            report.gap(2 * mm)
            report.text(text, font="Helvetica-Bold", size=12, color=BRAND_GREEN_DARK, leading=16)
        else:
            report.text(text, size=10, leading=13)


def build_agreement_pdf(order: dict[str, Any], kind: str, *, store_name: str) -> tuple[bytes, str]:
    spec = AGREEMENT_DOCUMENTS[kind]
    report = _Report()
    code = str(order.get("_id") or "")[-6:].upper()
    agreement = _agreement(order, kind)

    report.text("Pa' La Jaba", font="Helvetica-Bold", size=16, color=BRAND_GREEN_DARK, leading=20)
    report.text(spec["title"], font="Helvetica-Bold", size=14, color=BRAND_GREEN_DARK, leading=18)
    report.text(f"Pedido #{code} · {store_name or 'Tienda'}", size=11, leading=15)
    report.text("Texto aceptado al momento del pedido.", size=9, color=TEXT_MUTED, leading=12)
    report.rule()
    if agreement:
        accepted = _when(agreement.get("accepted_at")) if isinstance(agreement.get("accepted_at"), datetime) else ""
        if accepted and accepted != "—":
            report.text(f"Aceptado el {accepted}.", size=9, color=TEXT_MUTED, leading=12)
        _write_document(report, agreement.get("content"), spec["empty"])
    else:
        report.text(spec["empty"], color=TEXT_MUTED)
    return report.finish(), f"{spec['filename']}-{code}.pdf"
