from datetime import UTC, datetime, timedelta
import unittest

from app.services.product_popularity import (
    POPULARITY_DELTA,
    POPULARITY_WINDOW,
    popularity_cutoff,
    popularity_score,
)


class PopularityScoreTests(unittest.TestCase):
    def test_weights(self) -> None:
        self.assertEqual(POPULARITY_DELTA["view"], 1)
        self.assertEqual(POPULARITY_DELTA["jaba"], 2)
        self.assertEqual(POPULARITY_DELTA["purchase"], 3)

    def test_standard_plan_keeps_the_sum(self) -> None:
        self.assertEqual(popularity_score(1 + 2 + 3, premium=False), 6)

    def test_premium_plan_doubles_the_sum(self) -> None:
        self.assertEqual(popularity_score(6, premium=True), 12)

    def test_negative_points_do_not_reduce_below_zero(self) -> None:
        self.assertEqual(popularity_score(-4, premium=True), 0)

    def test_window_is_three_weeks(self) -> None:
        now = datetime(2026, 10, 8, 12, tzinfo=UTC)
        self.assertEqual(POPULARITY_WINDOW, timedelta(weeks=3))
        self.assertEqual(popularity_cutoff(now), datetime(2026, 9, 17, 12))


if __name__ == "__main__":
    unittest.main()
