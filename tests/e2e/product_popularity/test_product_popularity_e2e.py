"""Recorrido de popularidad: eventos reales, ventana de 3 semanas y boost Premium."""

from __future__ import annotations

import unittest

from bson import ObjectId

from tests.e2e.product_popularity.utils.fixtures import (
    STALE_EVENT_POINTS,
    PRODUCT_NAME,
    cleanup_db,
    count_events,
    headers_for,
    load_product_and_events,
    order_payload,
    seed_seller_and_product,
)
from tests.e2e.utils.api import api_client
from tests.e2e.utils.buyer_flow import complete_marketplace_order
from tests.e2e.utils.database import mongo_configured


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class ProductPopularityE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def _run_buyer_flow(self, plan_tier: str) -> tuple[dict, list[dict]]:
        seller_id, product_id = seed_seller_and_product(plan_tier)
        complete_marketplace_order(
            self,
            product_id=product_id,
            order_body=order_payload(seller_id=seller_id, product_id=product_id),
            seller_headers=headers_for(seller_id, plan_tier),
        )
        return load_product_and_events(product_id)

    def test_standard_plan_sums_only_the_last_three_weeks(self) -> None:
        product, events = self._run_buyer_flow("standard")
        recent = [event for event in events if event["points"] != STALE_EVENT_POINTS]

        self.assertEqual([event["event"] for event in recent], ["view", "jaba", "purchase"])
        self.assertEqual([event["points"] for event in recent], [1, 2, 3])
        self.assertEqual(product["name"], PRODUCT_NAME)
        self.assertEqual(product["popularity"], 6)

    def test_premium_plan_doubles_the_three_week_sum(self) -> None:
        product, events = self._run_buyer_flow("premium")
        recent_points = sum(
            event["points"] for event in events if event["points"] != STALE_EVENT_POINTS
        )

        self.assertEqual(recent_points, 6)
        self.assertEqual(product["popularity"], 12)

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
