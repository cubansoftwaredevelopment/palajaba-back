"""
Integración: refresco de tasas elTOQUE cada 20 minutos.

Verifica:
- intervalo por defecto (1200 s)
- no se llama a elTOQUE si el caché sigue fresco
- sí se refresca cuando el caché supera el intervalo
- GET /api/platform/exchange-rates expone tasas reales (rates_available)

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_exchange_rates_refresh_integration.py
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo, get_exchange_rates_collection
from app.routers import platform as platform_router
from app.services import exchange_rates as exchange_rates_service
from app.utils.datetime import to_utc_naive, utc_now

TWENTY_MINUTES = 20 * 60
ELTOQUE_PAYLOAD_V1 = {
    "tasas": {"USD": 410.0, "ECU": 445.0, "MLC": 390.0},
    "date": "2026-06-12",
    "hour": 10,
    "minutes": 15,
    "seconds": 0,
}
ELTOQUE_PAYLOAD_V2 = {
    "tasas": {"USD": 420.0, "ECU": 455.0, "MLC": 400.0},
    "date": "2026-06-12",
    "hour": 10,
    "minutes": 35,
    "seconds": 0,
}


def _reset_exchange_rates_state() -> None:
    exchange_rates_service._cup_per_unit_cache = {"CUP": 1.0}
    exchange_rates_service._rates_available = False
    exchange_rates_service._cache_meta = {
        "updated_at": None,
        "reference_date": None,
        "reference_time": None,
        "stale": True,
    }


async def _clear_persisted_rates() -> None:
    await get_exchange_rates_collection().delete_many({})


async def _seed_rates_from_eltoque(payload: dict) -> None:
    cup_per_unit, reference_date, reference_time = exchange_rates_service._normalize_eltoque_payload(payload)
    await exchange_rates_service._persist_rates(
        cup_per_unit,
        reference_date=reference_date,
        reference_time=reference_time,
        stale=False,
        rates_available=True,
    )


class ExchangeRatesRefreshIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        _reset_exchange_rates_state()
        await _clear_persisted_rates()

    async def asyncTearDown(self) -> None:
        _reset_exchange_rates_state()
        await _clear_persisted_rates()
        await close_mongo_connection()

    def test_default_refresh_interval_is_twenty_minutes(self) -> None:
        from app.config import Settings

        self.assertEqual(Settings.model_fields["exchange_rates_refresh_seconds"].default, TWENTY_MINUTES)

    def test_needs_refresh_uses_twenty_minute_window(self) -> None:
        now = utc_now()
        fresh = to_utc_naive(now - timedelta(minutes=19, seconds=59))
        stale = to_utc_naive(now - timedelta(minutes=20, seconds=1))

        with patch.object(settings, "exchange_rates_refresh_seconds", TWENTY_MINUTES):
            self.assertFalse(exchange_rates_service._needs_refresh(fresh))
            self.assertTrue(exchange_rates_service._needs_refresh(stale))

    async def test_refresh_skips_eltoque_when_cache_is_fresh(self) -> None:
        await _seed_rates_from_eltoque(ELTOQUE_PAYLOAD_V1)
        fetch_mock = AsyncMock(return_value=ELTOQUE_PAYLOAD_V2)

        with patch(
            "app.services.exchange_rates._fetch_eltoque_trmi",
            fetch_mock,
        ):
            public = await exchange_rates_service.refresh_exchange_rates(force=False)

        fetch_mock.assert_not_awaited()
        self.assertTrue(public.rates_available)
        self.assertEqual(public.cup_per_unit["USD"], 410.0)

    async def test_refresh_fetches_eltoque_when_cache_is_stale(self) -> None:
        await _seed_rates_from_eltoque(ELTOQUE_PAYLOAD_V1)
        stale_time = to_utc_naive(utc_now() - timedelta(minutes=21))
        exchange_rates_service._cache_meta["updated_at"] = stale_time

        fetch_mock = AsyncMock(return_value=ELTOQUE_PAYLOAD_V2)
        with (
            patch.object(settings, "exchange_rates_refresh_seconds", TWENTY_MINUTES),
            patch(
                "app.services.exchange_rates._fetch_eltoque_trmi",
                fetch_mock,
            ),
        ):
            public = await exchange_rates_service.refresh_exchange_rates(force=False)

        fetch_mock.assert_awaited_once()
        self.assertTrue(public.rates_available)
        self.assertEqual(public.cup_per_unit["USD"], 420.0)

        persisted = await get_exchange_rates_collection().find_one(
            {"_id": exchange_rates_service.CACHE_DOCUMENT_ID},
        )
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["cup_per_unit"]["USD"], 420.0)

    async def test_platform_exchange_rates_endpoint_exposes_real_rates(self) -> None:
        await _seed_rates_from_eltoque(ELTOQUE_PAYLOAD_V1)

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(platform_router.router)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/platform/exchange-rates")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["rates_available"])
        self.assertEqual(payload["cup_per_unit"]["USD"], 410.0)
        self.assertEqual(payload["cup_per_unit"]["EUR"], 445.0)
        self.assertEqual(payload["cup_per_unit"]["MLC"], 390.0)
        self.assertFalse(payload["stale"])

    async def test_refresh_failure_keeps_persisted_rates_without_mock_fallback(self) -> None:
        await _seed_rates_from_eltoque(ELTOQUE_PAYLOAD_V1)
        stale_time = to_utc_naive(utc_now() - timedelta(minutes=21))
        exchange_rates_service._cache_meta["updated_at"] = stale_time

        fetch_mock = AsyncMock(side_effect=RuntimeError("sin red"))
        with (
            patch.object(settings, "exchange_rates_refresh_seconds", TWENTY_MINUTES),
            patch(
                "app.services.exchange_rates._fetch_eltoque_trmi",
                fetch_mock,
            ),
        ):
            public = await exchange_rates_service.refresh_exchange_rates(force=False)

        self.assertTrue(public.rates_available)
        self.assertEqual(public.cup_per_unit["USD"], 410.0)
        self.assertNotEqual(public.cup_per_unit.get("USD"), 250.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
