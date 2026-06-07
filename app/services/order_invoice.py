from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.utils.currency_conversion import convert_amount, format_money
from app.utils.phone import phone_display

InvoiceType = Literal["store", "transporter"]

BRAND_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "brand" / "logo.png"

BRAND_GREEN = colors.HexColor("#59802C")
BRAND_GREEN_DARK = colors.HexColor("#3F5C1F")
BG_PAGE = colors.HexColor("#FFFFFF")
BG_SECTION = colors.HexColor("#F6F9F2")
BG_TABLE_HEAD = colors.HexColor("#E8F0DC")
TEXT_MUTED = colors.HexColor("#5C6B52")
ROW_ALT = colors.HexColor("#FAFCF7")
RULE = colors.HexColor("#D8E4C8")


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d/%m/%Y %H:%M")


def _payment_lines(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    payment_currency = doc.get("payment_currency")
    if not payment_currency:
        raise ValueError("Selecciona la moneda de pago antes de generar la factura.")

    lines: list[dict[str, Any]] = []
    products_total = 0.0

    for item in doc.get("items") or []:
        line_total = convert_amount(
            float(item["line_total"]),
            item["currency"],
            payment_currency,
        )
        unit_price = convert_amount(
            float(item["unit_price"]),
            item["currency"],
            payment_currency,
        )
        lines.append(
            {
                "name": item["name"],
                "quantity": item["quantity"],
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
        products_total += line_total

    delivery_total = 0.0
    if doc.get("delivery_requested") and doc.get("delivery_price") is not None:
        delivery_currency = doc.get("delivery_currency") or "CUP"
        delivery_total = convert_amount(
            float(doc["delivery_price"]),
            delivery_currency,
            payment_currency,
        )

    grand_total = products_total + delivery_total
    return lines, grand_total


def _draw_wrapped_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    font_name: str = "Helvetica",
    font_size: int = 10,
    line_height: float = 13,
) -> float:
    words = text.split()
    line = ""
    current_y = y

    for word in words:
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            line = candidate
        else:
            if line:
                pdf.drawString(x, current_y, line)
                current_y -= line_height
            line = word

    if line:
        pdf.drawString(x, current_y, line)
        current_y -= line_height

    return current_y


def _draw_header(
    pdf: canvas.Canvas,
    width: float,
    height: float,
    margin: float,
    doc_title: str,
    store_name: str,
    order_code: str,
) -> float:
    top = height - margin
    header_bottom = top - 30 * mm
    logo_size = 18 * mm
    logo_gap = 4 * mm
    title_baseline = top - 12 * mm
    subtitle_baseline = title_baseline - 6.5 * mm

    if BRAND_LOGO_PATH.is_file():
        text_block_center = (title_baseline + 3.5 * mm + subtitle_baseline - 1.5 * mm) / 2
        logo_bottom = text_block_center - (logo_size / 2)
        pdf.drawImage(
            str(BRAND_LOGO_PATH),
            margin,
            logo_bottom,
            width=logo_size,
            height=logo_size,
            preserveAspectRatio=True,
            mask="auto",
        )
        brand_x = margin + logo_size + logo_gap
    else:
        brand_x = margin

    pdf.setFillColor(BRAND_GREEN)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(brand_x, title_baseline, "Pa' La Jaba")

    pdf.setFillColor(TEXT_MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(brand_x, subtitle_baseline, "Marketplace local")

    pdf.setFillColor(BRAND_GREEN_DARK)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawRightString(width - margin, top - 12 * mm, doc_title)

    pdf.setFillColor(TEXT_MUTED)
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(width - margin, top - 19 * mm, f"Pedido #{order_code}")

    pdf.setStrokeColor(RULE)
    pdf.setLineWidth(1)
    pdf.line(margin, header_bottom, width - margin, header_bottom)

    pdf.setFillColor(BRAND_GREEN_DARK)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, header_bottom - 8 * mm, store_name)

    pdf.setFillColor(TEXT_MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(width - margin, header_bottom - 8 * mm, "Documento generado automáticamente")

    return header_bottom - 16 * mm


def _draw_meta_row(
    pdf: canvas.Canvas,
    margin: float,
    y: float,
    width: float,
    entries: list[tuple[str, str]],
) -> float:
    usable_width = width - (2 * margin)
    col_width = usable_width / max(len(entries), 1)
    x = margin

    for label, value in entries:
        pdf.setFillColor(TEXT_MUTED)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(x, y, label.upper())

        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(x, y - 5 * mm, value[:34])

        x += col_width

    return y - 14 * mm


def _draw_section_title(pdf: canvas.Canvas, margin: float, y: float, title: str) -> float:
    pdf.setFillColor(BRAND_GREEN_DARK)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, y, title)
    return y - 12


def _draw_buyer_location_section(
    pdf: canvas.Canvas,
    margin: float,
    y: float,
    content_width: float,
    buyer_zone: dict[str, Any],
) -> float:
    province = buyer_zone.get("province_name") or "—"
    municipality = buyer_zone.get("municipality_name") or "—"

    y = _draw_section_title(pdf, margin, y, "Ubicación del comprador")
    return _draw_info_box(
        pdf,
        margin,
        y,
        content_width,
        [
            ("Provincia", province),
            ("Municipio", municipality),
        ],
    )


def _draw_info_box(
    pdf: canvas.Canvas,
    margin: float,
    y: float,
    content_width: float,
    lines: list[tuple[str, str]],
) -> float:
    line_count = len(lines)
    box_height = 10 * mm + (line_count * 6 * mm)
    top = y

    pdf.setFillColor(BG_SECTION)
    pdf.roundRect(margin, top - box_height, content_width, box_height, 6, fill=1, stroke=0)

    current_y = top - 8 * mm
    for label, value in lines:
        pdf.setFillColor(BRAND_GREEN_DARK)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(margin + 10, current_y, f"{label}")
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", 10)
        current_y = _draw_wrapped_text(
            pdf,
            value,
            margin + 68,
            current_y,
            content_width - 78,
            line_height=12,
        )
        current_y -= 2.5 * mm

    return top - box_height - 8


def _draw_products_table(
    pdf: canvas.Canvas,
    margin: float,
    y: float,
    width: float,
    height: float,
    lines: list[dict[str, Any]],
    payment_currency: str,
) -> float:
    content_width = width - (2 * margin)
    col_product = margin + 10
    col_qty = margin + content_width * 0.58
    col_unit = margin + content_width * 0.72
    col_total = width - margin - 10
    row_height = 7.5 * mm

    table_top = y
    header_height = 8 * mm
    body_height = max(len(lines), 1) * row_height
    table_height = header_height + body_height + 2

    pdf.setStrokeColor(RULE)
    pdf.setLineWidth(0.6)
    pdf.roundRect(margin, table_top - table_height, content_width, table_height, 6, fill=0, stroke=1)

    pdf.setFillColor(BG_TABLE_HEAD)
    pdf.roundRect(margin, table_top - header_height, content_width, header_height, 6, fill=1, stroke=0)
    pdf.rect(margin, table_top - header_height, content_width, 3 * mm, fill=1, stroke=0)

    header_y = table_top - 5.5 * mm
    pdf.setFillColor(BRAND_GREEN_DARK)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(col_product, header_y, "Producto")
    pdf.drawCentredString(col_qty + 12, header_y, "Cant.")
    pdf.drawRightString(col_unit + 30, header_y, "Precio unit.")
    pdf.drawRightString(col_total, header_y, "Importe")

    current_y = table_top - header_height - 5
    pdf.setFont("Helvetica", 9)

    for index, line in enumerate(lines):
        if current_y < 72:
            pdf.showPage()
            _draw_page_background(pdf, width, height)
            current_y = height - margin - 24

        if index % 2 == 1:
            pdf.setFillColor(ROW_ALT)
            pdf.rect(margin + 1, current_y - row_height + 4, content_width - 2, row_height, fill=1, stroke=0)

        pdf.setFillColor(colors.black)
        name = line["name"][:40]
        pdf.drawString(col_product, current_y, name)
        pdf.drawCentredString(col_qty + 12, current_y, str(line["quantity"]))
        pdf.drawRightString(col_unit + 30, current_y, format_money(line["unit_price"], payment_currency))
        pdf.drawRightString(col_total, current_y, format_money(line["line_total"], payment_currency))
        current_y -= row_height

    return table_top - table_height - 10


def _draw_totals_block(
    pdf: canvas.Canvas,
    margin: float,
    y: float,
    width: float,
    payment_currency: str,
    products_total: float,
    delivery_total: float | None,
    grand_total: float,
) -> float:
    block_width = 84 * mm
    x = width - margin - block_width
    detail_height = 30 * mm if delivery_total is not None else 22 * mm
    total_band_height = 14 * mm
    block_height = detail_height + total_band_height

    pdf.setFillColor(BG_SECTION)
    pdf.roundRect(x, y - block_height, block_width, detail_height, 6, fill=1, stroke=0)

    current_y = y - 7 * mm
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.drawString(x + 10, current_y, "Subtotal productos")
    pdf.setFillColor(colors.black)
    pdf.drawRightString(width - margin - 10, current_y, format_money(products_total, payment_currency))
    current_y -= 7 * mm

    if delivery_total is not None:
        pdf.setFillColor(TEXT_MUTED)
        pdf.drawString(x + 10, current_y, "Domicilio")
        pdf.setFillColor(colors.black)
        pdf.drawRightString(width - margin - 10, current_y, format_money(delivery_total, payment_currency))
        current_y -= 7 * mm

    total_y = y - detail_height
    pdf.setFillColor(BRAND_GREEN)
    pdf.roundRect(x, total_y - total_band_height, block_width, total_band_height, 6, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x + 10, total_y - 9 * mm, "TOTAL A PAGAR")
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawRightString(width - margin - 10, total_y - 9.5 * mm, format_money(grand_total, payment_currency))

    return y - block_height - 12


def _draw_page_background(pdf: canvas.Canvas, width: float, height: float) -> None:
    pdf.setFillColor(BG_PAGE)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)


def _draw_footer(pdf: canvas.Canvas, width: float, margin: float, seller_phone: str) -> None:
    footer_height = 14 * mm
    pdf.setStrokeColor(RULE)
    pdf.setLineWidth(0.8)
    pdf.line(margin, footer_height + 4, width - margin, footer_height + 4)

    pdf.setFillColor(TEXT_MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin, footer_height - 1 * mm, f"Contacto de la tienda: {seller_phone}")

    if BRAND_LOGO_PATH.is_file():
        pdf.drawImage(
            str(BRAND_LOGO_PATH),
            width - margin - 10 * mm,
            footer_height - 2 * mm,
            width=8 * mm,
            height=8 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )
        pdf.drawRightString(width - margin - 12 * mm, footer_height - 1 * mm, "Pa' La Jaba")
    else:
        pdf.drawRightString(width - margin, footer_height - 1 * mm, "Pa' La Jaba")


def build_order_invoice_pdf(doc: dict[str, Any], seller_doc: dict[str, Any], invoice_type: InvoiceType) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 16 * mm
    content_width = width - (2 * margin)

    _draw_page_background(pdf, width, height)

    store_name = doc.get("store_name", "Tienda")
    order_code = str(doc["_id"])[-6:].upper()
    seller_phone = phone_display(seller_doc.get("phone", ""))
    payment_currency = doc.get("payment_currency")

    doc_title = "Factura de pedido" if invoice_type == "store" else "Hoja para transportista"
    y = _draw_header(pdf, width, height, margin, doc_title, store_name, order_code)

    meta_entries = [("Fecha del pedido", _format_datetime(doc.get("created_at")))]
    if payment_currency:
        meta_entries.append(("Moneda de pago", payment_currency))
    y = _draw_meta_row(pdf, margin, y, width, meta_entries[:3])

    buyer_zone = doc.get("buyer_zone")
    if buyer_zone:
        y = _draw_buyer_location_section(pdf, margin, y, content_width, buyer_zone)

    delivery = doc.get("delivery")
    if (invoice_type == "transporter" or doc.get("delivery_requested")) and delivery:
        y = _draw_section_title(pdf, margin, y, "Datos de entrega")
        delivery_lines = [
            ("Recibe", delivery.get("recipient_name", "—")),
            ("Dirección", delivery.get("address", "—")),
        ]
        phones = delivery.get("phone_primary", "")
        if delivery.get("phone_secondary"):
            phones = f"{phones}, {delivery['phone_secondary']}"
        delivery_lines.append(("Teléfono", phones or "—"))
        if delivery.get("notes"):
            delivery_lines.append(("Indicaciones", delivery["notes"]))
        y = _draw_info_box(pdf, margin, y, content_width, delivery_lines)

    if invoice_type == "store":
        lines, grand_total = _payment_lines(doc)
        y = _draw_section_title(pdf, margin, y, "Detalle de productos")
        y = _draw_products_table(pdf, margin, y, width, height, lines, payment_currency)

        products_total = sum(line["line_total"] for line in lines)
        delivery_total = None
        if doc.get("delivery_requested") and doc.get("delivery_price") is not None:
            delivery_currency = doc.get("delivery_currency") or "CUP"
            delivery_total = convert_amount(
                float(doc["delivery_price"]),
                delivery_currency,
                payment_currency,
            )

        _draw_totals_block(
            pdf,
            margin,
            y,
            width,
            payment_currency,
            products_total,
            delivery_total,
            grand_total,
        )
    else:
        y = _draw_section_title(pdf, margin, y, "Productos a entregar")
        items = doc.get("items") or []
        box_height = 10 * mm + (max(len(items), 1) * 6.5 * mm)
        pdf.setFillColor(BG_SECTION)
        pdf.roundRect(margin, y - box_height, content_width, box_height, 6, fill=1, stroke=0)
        current_y = y - 9 * mm
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(colors.black)
        for item in items:
            pdf.drawString(margin + 12, current_y, f"• {item['name']}  ×  {item['quantity']}")
            current_y -= 6.5 * mm
        y -= box_height + 8

        if payment_currency:
            try:
                _, grand_total = _payment_lines(doc)
                pdf.setFillColor(BRAND_GREEN)
                pdf.roundRect(margin, y - 16 * mm, content_width, 16 * mm, 6, fill=1, stroke=0)
                pdf.setFillColor(colors.white)
                pdf.setFont("Helvetica-Bold", 10)
                pdf.drawString(margin + 12, y - 7 * mm, "Total a cobrar / entregar")
                pdf.setFont("Helvetica-Bold", 14)
                pdf.drawRightString(
                    width - margin - 12,
                    y - 8 * mm,
                    format_money(grand_total, payment_currency),
                )
                y -= 22 * mm
            except ValueError:
                pass

    _draw_footer(pdf, width, margin, seller_phone)

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()
