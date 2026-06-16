"""
Tests de actualización de teléfono del vendedor.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_seller_phone_update.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.seller_profile import SellerPhoneUpdate
from app.utils.phone import normalize_phone_digits


class NormalizePhoneDigitsTests(unittest.TestCase):
    def test_accepts_eight_digits(self) -> None:
        self.assertEqual(normalize_phone_digits("51234567"), "51234567")

    def test_strips_country_prefix(self) -> None:
        self.assertEqual(normalize_phone_digits("+53 5123 4567"), "51234567")

    def test_rejects_short_number(self) -> None:
        with self.assertRaises(ValueError):
            normalize_phone_digits("123")


class SellerPhoneUpdateSchemaTests(unittest.TestCase):
    def test_normalizes_payload(self) -> None:
        payload = SellerPhoneUpdate(phone="+53 5987 6543")
        self.assertEqual(payload.phone, "59876543")

    def test_rejects_invalid_phone(self) -> None:
        with self.assertRaises(ValueError):
            SellerPhoneUpdate(phone="123")


class UpdateSellerPhoneServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_phone_when_unique(self) -> None:
        from app.services import seller_profile as profile_service

        seller_id = str(ObjectId())
        object_id = ObjectId(seller_id)
        doc = {
            "_id": object_id,
            "store_name": "Ferretería",
            "phone": "51234567",
            "status": "approved",
            "billing_period": "monthly",
            "plan_tier": "standard",
            "profile_photo_url": "https://example.com/photo.jpg",
            "category_ids": ["construccion"],
            "offers_delivery": False,
            "business_area": {
                "province_id": "la-habana",
                "province_name": "La Habana",
                "municipality_id": "playa",
                "municipality_name": "Playa",
            },
            "subscription_ends_at": None,
        }
        updated_doc = {**doc, "phone": "59876543"}

        collection = AsyncMock()
        collection.find_one = AsyncMock(side_effect=[doc, None, updated_doc])
        collection.update_one = AsyncMock()

        with patch.object(profile_service, "get_registrations_collection", return_value=collection):
            result = await profile_service.update_seller_phone(
                seller_id,
                SellerPhoneUpdate(phone="59876543"),
            )

        self.assertEqual(result.phone, "+5359876543")
        collection.update_one.assert_awaited_once()
        update_args = collection.update_one.await_args
        self.assertEqual(update_args.args[1]["$set"]["phone"], "59876543")

    async def test_noop_when_phone_unchanged(self) -> None:
        from app.services import seller_profile as profile_service

        seller_id = str(ObjectId())
        doc = {
            "_id": ObjectId(seller_id),
            "store_name": "Ferretería",
            "phone": "51234567",
            "status": "approved",
            "billing_period": "monthly",
            "plan_tier": "standard",
            "profile_photo_url": "https://example.com/photo.jpg",
            "category_ids": ["construccion"],
            "offers_delivery": False,
            "business_area": {
                "province_id": "la-habana",
                "province_name": "La Habana",
                "municipality_id": "playa",
                "municipality_name": "Playa",
            },
            "subscription_ends_at": None,
        }

        collection = AsyncMock()
        collection.find_one = AsyncMock(return_value=doc)
        collection.update_one = AsyncMock()

        with patch.object(profile_service, "get_registrations_collection", return_value=collection):
            result = await profile_service.update_seller_phone(
                seller_id,
                SellerPhoneUpdate(phone="51234567"),
            )

        self.assertEqual(result.phone, "+5351234567")
        collection.update_one.assert_not_awaited()

    async def test_rejects_duplicate_phone(self) -> None:
        from app.services import seller_profile as profile_service

        seller_id = str(ObjectId())
        object_id = ObjectId(seller_id)
        doc = {
            "_id": object_id,
            "store_name": "Ferretería",
            "phone": "51234567",
            "status": "approved",
            "billing_period": "monthly",
            "plan_tier": "standard",
            "profile_photo_url": "https://example.com/photo.jpg",
            "category_ids": ["construccion"],
            "offers_delivery": False,
            "business_area": {
                "province_id": "la-habana",
                "province_name": "La Habana",
                "municipality_id": "playa",
                "municipality_name": "Playa",
            },
            "subscription_ends_at": None,
        }

        collection = AsyncMock()
        collection.find_one = AsyncMock(side_effect=[doc, {"_id": ObjectId()}])

        with patch.object(profile_service, "get_registrations_collection", return_value=collection):
            with self.assertRaises(HTTPException) as ctx:
                await profile_service.update_seller_phone(
                    seller_id,
                    SellerPhoneUpdate(phone="59876543"),
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("ya está registrado", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
