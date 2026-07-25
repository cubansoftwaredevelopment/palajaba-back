from __future__ import annotations

import unittest
from datetime import datetime

from app.services.cuba_time import (
    cuba_date_str,
    cuba_hour,
    cuba_hour_label,
    cuba_weekday,
    cuba_weekday_label,
    to_cuba_local,
)


class CubaTimeUnitTests(unittest.TestCase):
    def test_to_cuba_local_subtracts_four_hours(self) -> None:
        utc = datetime(2026, 7, 25, 16, 30, 0)
        local = to_cuba_local(utc)
        self.assertEqual(local, datetime(2026, 7, 25, 12, 30, 0))

    def test_cuba_date_rolls_back_near_midnight_utc(self) -> None:
        utc = datetime(2026, 7, 26, 2, 0, 0)
        self.assertEqual(cuba_date_str(utc), "2026-07-25")
        self.assertEqual(cuba_hour(utc), 22)
        self.assertEqual(cuba_weekday(utc), 5)  # sábado

    def test_labels(self) -> None:
        self.assertEqual(cuba_hour_label(9), "09:00")
        self.assertEqual(cuba_weekday_label(0), "Lun")
        self.assertEqual(cuba_weekday_label(6), "Dom")
        with self.assertRaises(ValueError):
            cuba_weekday_label(7)


if __name__ == "__main__":
    unittest.main()
