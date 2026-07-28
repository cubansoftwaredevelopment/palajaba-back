from __future__ import annotations

import unittest

from app.services.gestores import gestor_limit_reached_detail
from app.services.plans import (
    STANDARD_GESTOR_LIMIT,
    max_gestores_for_plan,
    seller_can_add_gestor,
)


class GestorPlanLimitUnitTests(unittest.TestCase):
    def test_basic_plan_limit_is_three(self) -> None:
        self.assertEqual(max_gestores_for_plan("standard"), STANDARD_GESTOR_LIMIT)
        self.assertEqual(max_gestores_for_plan(None), 3)
        self.assertEqual(STANDARD_GESTOR_LIMIT, 3)

    def test_premium_plan_is_unlimited(self) -> None:
        self.assertIsNone(max_gestores_for_plan("premium"))

    def test_seller_can_add_gestor_respects_basic_cap(self) -> None:
        self.assertTrue(seller_can_add_gestor("standard", 0))
        self.assertTrue(seller_can_add_gestor("standard", 2))
        self.assertFalse(seller_can_add_gestor("standard", 3))
        self.assertFalse(seller_can_add_gestor("standard", 10))

    def test_seller_can_add_gestor_premium_never_blocks(self) -> None:
        self.assertTrue(seller_can_add_gestor("premium", 0))
        self.assertTrue(seller_can_add_gestor("premium", 99))

    def test_limit_detail_mentions_upgrade(self) -> None:
        detail = gestor_limit_reached_detail(3)
        self.assertIn("3", detail)
        self.assertIn("Premium", detail)


if __name__ == "__main__":
    unittest.main()
