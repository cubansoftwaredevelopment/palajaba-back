"""Recorrido de popularidad: eventos reales, ventana de 3 semanas y boost Premium."""

from __future__ import annotations

import unittest

from bson import ObjectId

from test_e2e.product_popularity.utils.fixtures import (
    STALE_EVENT_POINTS,
    PRODUCT_NAME,
    cleanup_db,
    count_events,
    run_buyer_popularity_flow,
)
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ProductPopularityE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_standard_plan_sums_only_the_last_three_weeks(self) -> None:
        product, events = run_buyer_popularity_flow(self, "standard")
        recent = [event for event in events if event["points"] != STALE_EVENT_POINTS]

        self.assertEqual([event["event"] for event in recent], ["view", "jaba", "purchase"])
        self.assertEqual([event["points"] for event in recent], [1, 2, 3])
        self.assertEqual(product["name"], PRODUCT_NAME)
        self.assertEqual(product["popularity"], 6)

    def test_pro_plan_doubles_the_three_week_sum(self) -> None:
        product, events = run_buyer_popularity_flow(self, "pro")
        recent_points = sum(
            event["points"] for event in events if event["points"] != STALE_EVENT_POINTS
        )

        self.assertEqual(recent_points, 6)
        self.assertEqual(product["popularity"], 12)

    def test_premium_plan_quadruples_the_three_week_sum(self) -> None:
        product, events = run_buyer_popularity_flow(self, "premium")
        recent_points = sum(
            event["points"] for event in events if event["points"] != STALE_EVENT_POINTS
        )

        self.assertEqual(recent_points, 6)
        self.assertEqual(product["popularity"], 24)

    def test_unknown_product_does_not_record_an_event(self) -> None:
        missing_id = str(ObjectId())
        with api_client() as client:
            response = client.post(
                f"/api/marketplace/products/{missing_id}/popularity",
                json={"event": "view"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(count_events(missing_id), 0)


if __name__ == "__main__":
    unittest.main()
