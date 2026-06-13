"""
Tests de la promoción de lanzamiento (primeros 30 usuarios).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_launch_promo.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.constants import LAUNCH_PROMO_LIMIT
from app.services.launch_promo import build_launch_promo_status


class LaunchPromoStatusTests(unittest.TestCase):
    def test_available_when_under_limit(self) -> None:
        status = build_launch_promo_status(12)
        self.assertTrue(status.available)
        self.assertEqual(status.slots_remaining, LAUNCH_PROMO_LIMIT - 12)

    def test_unavailable_when_limit_reached(self) -> None:
        status = build_launch_promo_status(LAUNCH_PROMO_LIMIT)
        self.assertFalse(status.available)
        self.assertEqual(status.slots_remaining, 0)


class LaunchPromoRegisterRequestTests(unittest.TestCase):
    def test_rejects_invalid_phone(self) -> None:
        from app.schemas.launch_promo import LaunchPromoRegisterRequest

        with self.assertRaises(ValueError):
            LaunchPromoRegisterRequest(
                store_name="Mi Tienda",
                phone="123",
                password="secret1",
            )

    def test_normalizes_phone(self) -> None:
        from app.schemas.launch_promo import LaunchPromoRegisterRequest

        payload = LaunchPromoRegisterRequest(
            store_name="Mi Tienda",
            phone="+53 5123 4567",
            password="secret1",
        )
        self.assertEqual(payload.phone, "51234567")


class LaunchPromoClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_when_promo_exhausted(self) -> None:
        from app.services import launch_promo as launch_promo_service

        from fastapi import HTTPException

        with patch.object(
            launch_promo_service,
            "_claim_launch_promo_slot",
            new=AsyncMock(return_value=False),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await launch_promo_service.create_launch_promo_registration(
                    store_name="Tienda Promo",
                    phone="51234567",
                    password="secret1",
                )

        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
