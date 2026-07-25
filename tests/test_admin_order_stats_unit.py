from __future__ import annotations

import unittest
from datetime import datetime

from app.services.admin_order_stats import (
    _bucket_orders,
    _daily_ranges_in_month,
    _period_window_for_granularity,
)
from app.services.seller_stats import resolve_comparison_window


class AdminOrderStatsUnitTests(unittest.TestCase):
    def test_bucket_orders_counts_completed_days(self) -> None:
        ranges = _daily_ranges_in_month(2026, 7, cap_at=datetime(2026, 7, 4))
        orders = [
            {"completed_at": datetime(2026, 7, 1, 10, 0, 0)},
            {"completed_at": datetime(2026, 7, 1, 22, 0, 0)},
            {"completed_at": datetime(2026, 7, 2, 8, 0, 0)},
            {"completed_at": datetime(2026, 7, 5, 8, 0, 0)},
        ]
        buckets = _bucket_orders(orders, ranges)
        self.assertEqual(buckets["2026-07-01"], 2)
        self.assertEqual(buckets["2026-07-02"], 1)
        self.assertEqual(buckets["2026-07-03"], 0)

    def test_period_window_matches_comparison_window(self) -> None:
        for granularity in ("daily", "weekly", "monthly"):
            start, end, label, year, month = _period_window_for_granularity(granularity)
            window = resolve_comparison_window(granularity)
            self.assertEqual(start, window.current_start)
            self.assertEqual(end, window.current_end)
            self.assertEqual(label, window.period_label)
            self.assertEqual(year, window.current_start.year)
            self.assertEqual(month, window.current_start.month)


if __name__ == "__main__":
    unittest.main()
