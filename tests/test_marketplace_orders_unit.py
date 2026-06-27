from __future__ import annotations

import unittest

from app.services import orders as orders_service


class MarketplaceOrdersUnitTests(unittest.TestCase):
    def test_calc_subtotals_groups_by_currency(self) -> None:
        items = [
            {"currency": "CUP", "unit_price": 100.0, "quantity": 2},
            {"currency": "USD", "unit_price": 5.0, "quantity": 1},
            {"currency": "CUP", "unit_price": 50.0, "quantity": 1},
        ]

        subtotals = orders_service._calc_subtotals(items)

        self.assertEqual(len(subtotals), 2)
        self.assertEqual(subtotals[0].currency, "CUP")
        self.assertEqual(subtotals[0].amount, 250.0)
        self.assertEqual(subtotals[1].currency, "USD")
        self.assertEqual(subtotals[1].amount, 5.0)

    def test_normalize_items_computes_line_total(self) -> None:
        normalized = orders_service._normalize_items(
            [
                {
                    "product_id": "abc",
                    "name": "Arroz",
                    "quantity": 3,
                    "unit_price": 10.5,
                    "currency": "CUP",
                }
            ]
        )

        self.assertEqual(normalized[0]["line_total"], 31.5)
        self.assertEqual(normalized[0]["product_id"], "abc")


if __name__ == "__main__":
    unittest.main()
