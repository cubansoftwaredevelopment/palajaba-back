from __future__ import annotations

import unittest

from app.services.discount_codes import (
    apply_percent_discount,
    normalize_discount_code,
)


class DiscountCodeHelpersTests(unittest.TestCase):
    def test_normalize_discount_code_uppercases_and_trims(self) -> None:
        self.assertEqual(normalize_discount_code('  amigo20 '), 'AMIGO20')

    def test_apply_percent_discount_rounds_down(self) -> None:
        self.assertEqual(apply_percent_discount(1000, 20), 800)
        self.assertEqual(apply_percent_discount(999, 15), 849)

    def test_apply_percent_discount_handles_full_discount(self) -> None:
        self.assertEqual(apply_percent_discount(5000, 100), 0)

    def test_apply_percent_discount_zero_percent_returns_original(self) -> None:
        self.assertEqual(apply_percent_discount(1200, 0), 1200)


if __name__ == "__main__":
    unittest.main()
