from __future__ import annotations

import unittest
from datetime import datetime

from app.services.order_totals import compute_order_grand_total, compute_order_products_revenue
from app.services.seller_stats import normalize_currency_totals


class NormalizeCurrencyTotalsTests(unittest.TestCase):
    def test_returns_all_currencies_with_zero_defaults(self) -> None:
        totals, orders_count = normalize_currency_totals([])
        self.assertEqual(orders_count, 0)
        self.assertEqual([item.currency for item in totals], ["USD", "MLC", "EUR", "CUP"])
        self.assertTrue(all(item.amount == 0.0 for item in totals))

    def test_maps_aggregation_rows_to_currency_totals(self) -> None:
        rows = [
            {"_id": "USD", "total": 120.5, "orders_count": 2},
            {"_id": "CUP", "total": 3000.4, "orders_count": 1},
        ]
        totals, orders_count = normalize_currency_totals(rows)
        by_currency = {item.currency: item.amount for item in totals}
        self.assertEqual(by_currency["USD"], 120.5)
        self.assertEqual(by_currency["CUP"], 3000.0)
        self.assertEqual(by_currency["MLC"], 0.0)
        self.assertEqual(by_currency["EUR"], 0.0)
        self.assertEqual(orders_count, 3)


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
