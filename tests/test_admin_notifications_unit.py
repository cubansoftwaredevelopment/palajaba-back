from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.schemas.notifications import AdminNotificationCreate
from app.services.notifications import _filter_sellers_by_audience


class AdminNotificationCreateUnitTests(unittest.TestCase):
    def test_seller_id_forces_single_audience(self) -> None:
        payload = AdminNotificationCreate(
            title="Aviso",
            content="Mensaje de prueba",
            audience="all",
            seller_id="507f1f77bcf86cd799439011",
        )
        self.assertEqual(payload.audience, "single")
        self.assertEqual(payload.seller_id, "507f1f77bcf86cd799439011")

    def test_single_without_seller_id_fails(self) -> None:
        with self.assertRaises(ValidationError):
            AdminNotificationCreate(
                title="Aviso",
                content="Mensaje de prueba",
                audience="single",
            )

    def test_strips_blank_seller_id(self) -> None:
        payload = AdminNotificationCreate(
            title="Aviso",
            content="Mensaje de prueba",
            audience="premium_monthly",
            seller_id="   ",
        )
        self.assertIsNone(payload.seller_id)
        self.assertEqual(payload.audience, "premium_monthly")


class AudienceFilterUnitTests(unittest.TestCase):
    def test_filter_premium_monthly(self) -> None:
        sellers = [
            {"plan_tier": "premium", "billing_period": "monthly"},
            {"plan_tier": "premium", "billing_period": "yearly"},
            {"plan_tier": "standard", "billing_period": "monthly"},
        ]
        filtered = _filter_sellers_by_audience(sellers, "premium_monthly")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["billing_period"], "monthly")


if __name__ == "__main__":
    unittest.main()
