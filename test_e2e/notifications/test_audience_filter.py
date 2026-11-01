"""El aviso SMS solo cubre los negocios del criterio elegido."""

from __future__ import annotations

import unittest

from app.notifications.schemas.admin import AdminNotificationCreate
from app.notifications.service import (
    _explicit_store_names,
    _filter_sellers_by_audiences,
    _stored_audience,
)
from test_e2e.notifications.utils.fixtures import audience_sellers


class AudienceFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sellers = audience_sellers()

    def test_multiple_groups_do_not_include_everyone(self) -> None:
        matched = _filter_sellers_by_audiences(
            self.sellers,
            ["premium_monthly", "pro_yearly"],
        )
        self.assertEqual([row["_id"] for row in matched], ["p-m"])

    def test_all_keeps_every_active_seller(self) -> None:
        matched = _filter_sellers_by_audiences(self.sellers, ["all"])
        self.assertEqual(len(matched), 4)

    def test_create_accepts_several_specific_stores(self) -> None:
        payload = AdminNotificationCreate(
            title="Aviso",
            content="Texto del aviso",
            audience="single",
            seller_ids=["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"],
        )
        self.assertEqual(
            payload.seller_ids,
            ["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"],
        )
        self.assertEqual(payload.audience, "single")
        self.assertIsNone(payload.seller_id)

    def test_explicit_store_names_keeps_selected_order(self) -> None:
        sellers = [
            {"_id": "aaa", "store_name": "Los Reyes"},
            {"_id": "bbb", "store_name": "Sasha"},
            {"_id": "ccc", "store_name": "Otra"},
        ]
        self.assertEqual(
            _explicit_store_names(sellers, ["bbb", "aaa"]),
            ["Sasha", "Los Reyes"],
        )

    def test_stored_audience_for_selection(self) -> None:
        self.assertEqual(_stored_audience(["premium_monthly", "pro_yearly"], []), "mixed")
        self.assertEqual(_stored_audience([], ["abc"]), "single")
        self.assertEqual(_stored_audience(["all"], []), "all")
