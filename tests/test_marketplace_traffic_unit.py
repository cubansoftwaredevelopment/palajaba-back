from __future__ import annotations

import unittest
from datetime import datetime

from pydantic import ValidationError

from app.schemas.marketplace_traffic import MarketplaceVisitRequest
from app.services.marketplace_traffic import _bucket_visits, _daily_ranges_in_month


class MarketplaceVisitRequestUnitTests(unittest.TestCase):
    def test_accepts_valid_payload(self) -> None:
        payload = MarketplaceVisitRequest(
            session_id="abc12345session",
            province_id="la-habana",
            municipality_id="plaza-de-la-revolucion",
        )
        self.assertEqual(payload.page, "marketplace")
        self.assertEqual(payload.session_id, "abc12345session")

    def test_rejects_short_session(self) -> None:
        with self.assertRaises(ValidationError):
            MarketplaceVisitRequest(
                session_id="short",
                province_id="la-habana",
                municipality_id="plaza-de-la-revolucion",
            )

    def test_rejects_invalid_session_chars(self) -> None:
        with self.assertRaises(ValidationError):
            MarketplaceVisitRequest(
                session_id="bad session!!",
                province_id="la-habana",
                municipality_id="plaza-de-la-revolucion",
            )


class MarketplaceTrafficBucketUnitTests(unittest.TestCase):
    def test_bucket_visits_counts_by_day(self) -> None:
        ranges = _daily_ranges_in_month(2026, 7, cap_at=datetime(2026, 7, 4))
        visits = [
            {"viewed_at": datetime(2026, 7, 1, 15, 0, 0)},
            {"viewed_at": datetime(2026, 7, 1, 18, 0, 0)},
            {"viewed_at": datetime(2026, 7, 2, 10, 0, 0)},
            {"viewed_at": datetime(2026, 7, 5, 10, 0, 0)},  # fuera del cap
        ]
        buckets = _bucket_visits(visits, ranges)
        self.assertEqual(buckets["2026-07-01"], 2)
        self.assertEqual(buckets["2026-07-02"], 1)
        self.assertEqual(buckets["2026-07-03"], 0)
        self.assertNotIn("2026-07-05", buckets)


if __name__ == "__main__":
    unittest.main()
