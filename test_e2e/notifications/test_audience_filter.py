"""El aviso SMS solo cubre los negocios del criterio elegido."""

from __future__ import annotations

import unittest

from app.notifications.service import _filter_sellers_by_audiences, _stored_audience
from app.subscriptions.service import PREMIUM_PLAN_TIER, PRO_PLAN_TIER, STANDARD_PLAN_TIER


def _seller(seller_id: str, tier: str, billing: str) -> dict:
    return {"_id": seller_id, "plan_tier": tier, "billing_period": billing}


class AudienceFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sellers = [
            _seller("p-m", PREMIUM_PLAN_TIER, "monthly"),
            _seller("p-y", PREMIUM_PLAN_TIER, "yearly"),
            _seller("pro-m", PRO_PLAN_TIER, "monthly"),
            _seller("std-m", STANDARD_PLAN_TIER, "monthly"),
        ]

    def test_multiple_groups_do_not_include_everyone(self) -> None:
        matched = _filter_sellers_by_audiences(
            self.sellers,
            ["premium_monthly", "pro_yearly"],
        )
        self.assertEqual([row["_id"] for row in matched], ["p-m"])

    def test_all_keeps_every_active_seller(self) -> None:
        matched = _filter_sellers_by_audiences(self.sellers, ["all"])
        self.assertEqual(len(matched), 4)

    def test_stored_audience_for_selection(self) -> None:
        self.assertEqual(_stored_audience(["premium_monthly", "pro_yearly"], []), "mixed")
        self.assertEqual(_stored_audience([], ["abc"]), "single")
        self.assertEqual(_stored_audience(["all"], []), "all")
