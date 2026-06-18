"""
Tests del parser de tasas elTOQUE.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_exchange_rates.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.exchange_rates import _normalize_eltoque_payload
from app.utils.currency_conversion import convert_amount


class NormalizeEltoquePayloadTests(unittest.TestCase):
    def test_maps_ecu_to_eur(self) -> None:
        cup_per_unit, reference_date, reference_time = _normalize_eltoque_payload(
            {
                "tasas": {"USD": 655.0, "ECU": 750.0, "MLC": 440.0},
                "date": "2026-06-12",
                "hour": 20,
                "minutes": 48,
                "seconds": 25,
            }
        )
        self.assertEqual(cup_per_unit["CUP"], 1.0)
        self.assertEqual(cup_per_unit["USD"], 655.0)
        self.assertEqual(cup_per_unit["EUR"], 750.0)
        self.assertEqual(cup_per_unit["MLC"], 440.0)
        self.assertEqual(reference_date, "2026-06-12")
        self.assertEqual(reference_time, "20:48:25")

    def test_requires_all_supported_currencies(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_eltoque_payload({"tasas": {"USD": 100.0}})


class CurrencyConversionTests(unittest.TestCase):
    def test_convert_usd_to_cup_using_cache(self) -> None:
        from app.services import exchange_rates as exchange_rates_service

        exchange_rates_service._cup_per_unit_cache.update(
            {"CUP": 1.0, "USD": 100.0, "EUR": 110.0, "MLC": 90.0}
        )
        exchange_rates_service._rates_available = True
        self.assertEqual(convert_amount(2, "USD", "CUP"), 200.0)
        self.assertEqual(convert_amount(200, "CUP", "USD"), 2.0)

    def test_public_rates_unavailable_without_real_cache(self) -> None:
        from app.services import exchange_rates as exchange_rates_service

        exchange_rates_service._cup_per_unit_cache = {"CUP": 1.0}
        exchange_rates_service._rates_available = False
        public = exchange_rates_service.build_exchange_rates_public()
        self.assertFalse(public.rates_available)
        self.assertEqual(public.cup_per_unit, {"CUP": 1.0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
