from typing import Any

from app.utils.currency_conversion import convert_amount


def compute_order_products_revenue(doc: dict[str, Any]) -> tuple[str, float] | None:
    """Total de productos cobrados (sin domicilio) en moneda de pago."""
    if doc.get("status") != "completed":
        return None

    payment_currency = doc.get("payment_currency")
    if not payment_currency:
        return None

    products_total = 0.0
    for item in doc.get("items") or []:
        products_total += convert_amount(
            float(item["line_total"]),
            item["currency"],
            payment_currency,
        )

    return payment_currency, round(products_total, 2)


def compute_order_grand_total(doc: dict[str, Any]) -> tuple[str, float] | None:
    """Total cobrado en moneda de pago para pedidos completados (incluye domicilio)."""
    revenue = compute_order_products_revenue(doc)
    if revenue is None:
        return None

    payment_currency, products_total = revenue

    delivery_total = 0.0
    if doc.get("delivery_requested") and doc.get("delivery_price") is not None:
        delivery_currency = doc.get("delivery_currency") or "CUP"
        delivery_total = convert_amount(
            float(doc["delivery_price"]),
            delivery_currency,
            payment_currency,
        )

    return payment_currency, round(products_total + delivery_total, 2)
