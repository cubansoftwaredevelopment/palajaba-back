from __future__ import annotations

import unittest

from app.services.orders import _normalize_items, _resolve_payment_currency


class ManualOrderHelpersTests(unittest.TestCase):
    def test_resolve_payment_currency_infers_single_currency(self) -> None:
        items = _normalize_items(
            [
                {
                    "product_id": "p1",
                    "name": "Arroz",
                    "quantity": 2,
                    "unit_price": 100.0,
                    "currency": "CUP",
                }
            ]
        )
        self.assertEqual(_resolve_payment_currency(items, None), "CUP")

    def test_normalize_items_calculates_line_total(self) -> None:
        items = _normalize_items(
            [
                {
                    "product_id": "p1",
                    "name": "Arroz",
                    "quantity": 3,
                    "unit_price": 50.0,
                    "currency": "USD",
                }
            ]
        )
        self.assertEqual(items[0]["line_total"], 150.0)
