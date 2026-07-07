from __future__ import annotations

import unittest

from app.services.order_totals import compute_order_grand_total, compute_order_products_revenue


class OrderRevenueTotalsTests(unittest.TestCase):
    def test_products_revenue_excludes_delivery(self) -> None:
        doc = {
            "status": "completed",
            "payment_currency": "USD",
            "items": [
                {
                    "line_total": 100.0,
                    "currency": "USD",
                }
            ],
            "delivery_requested": True,
            "delivery_price": 25.0,
            "delivery_currency": "USD",
        }
        products = compute_order_products_revenue(doc)
        grand = compute_order_grand_total(doc)
        self.assertEqual(products, ("USD", 100.0))
        self.assertEqual(grand, ("USD", 125.0))

    def test_products_revenue_returns_none_for_pending_order(self) -> None:
        doc = {
            "status": "pending_confirmation",
            "payment_currency": "CUP",
            "items": [{"line_total": 100.0, "currency": "CUP"}],
        }
        self.assertIsNone(compute_order_products_revenue(doc))

    def test_products_revenue_converts_line_items_to_payment_currency(self) -> None:
        from app.services import exchange_rates as exchange_rates_service

        exchange_rates_service._cup_per_unit_cache.update(
            {"CUP": 1.0, "USD": 400.0, "EUR": 450.0, "MLC": 300.0},
        )
        exchange_rates_service._rates_available = True
        try:
            doc = {
                "status": "completed",
                "payment_currency": "USD",
                "items": [
                    {"line_total": 400.0, "currency": "CUP"},
                    {"line_total": 10.0, "currency": "USD"},
                ],
            }
            revenue = compute_order_products_revenue(doc)
            self.assertIsNotNone(revenue)
            currency, amount = revenue
            self.assertEqual(currency, "USD")
            self.assertEqual(amount, 11.0)
        finally:
            exchange_rates_service._cup_per_unit_cache = {"CUP": 1.0}
            exchange_rates_service._rates_available = False
