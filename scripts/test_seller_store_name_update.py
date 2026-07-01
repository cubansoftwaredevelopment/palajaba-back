"""
Tests de actualización del nombre del negocio del vendedor.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_seller_store_name_update.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.seller_profile import SellerStoreNameUpdate
from app.utils.store_slug import store_name_to_slug


class SellerStoreNameUpdateSchemaTests(unittest.TestCase):
    def test_strips_store_name(self) -> None:
        payload = SellerStoreNameUpdate(store_name="  Mi Tienda  ")
        self.assertEqual(payload.store_name, "Mi Tienda")

    def test_rejects_empty_store_name(self) -> None:
        with self.assertRaises(ValueError):
            SellerStoreNameUpdate(store_name="   ")


class UpdateSellerStoreNameServiceTests(unittest.IsolatedAsyncioTestCase):
    def _seller_doc(self, seller_id: str) -> dict:
        object_id = ObjectId(seller_id)
        return {
            "_id": object_id,
            "store_name": "Ferretería",
            "store_slug": "ferreteria",
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

    async def test_updates_store_name_when_unique(self) -> None:
        from app.services import seller_profile as profile_service

        seller_id = str(ObjectId())
        doc = self._seller_doc(seller_id)
        updated_doc = {
            **doc,
            "store_name": "Ferretería Nueva",
            "store_slug": store_name_to_slug("Ferretería Nueva"),
        }

        collection = AsyncMock()
        collection.find_one = AsyncMock(side_effect=[doc, None, updated_doc])
        collection.update_one = AsyncMock()

        with patch.object(profile_service, "get_registrations_collection", return_value=collection):
            result = await profile_service.update_seller_store_name(
                seller_id,
                SellerStoreNameUpdate(store_name="Ferretería Nueva"),
            )

        self.assertEqual(result.store_name, "Ferretería Nueva")
        collection.update_one.assert_awaited_once()
        update_args = collection.update_one.await_args
        self.assertEqual(update_args.args[1]["$set"]["store_name"], "Ferretería Nueva")
        self.assertEqual(
            update_args.args[1]["$set"]["store_slug"],
            store_name_to_slug("Ferretería Nueva"),
        )

    async def test_noop_when_store_name_unchanged_case_insensitive(self) -> None:
        from app.services import seller_profile as profile_service

        seller_id = str(ObjectId())
        doc = self._seller_doc(seller_id)

        collection = AsyncMock()
        collection.find_one = AsyncMock(return_value=doc)
        collection.update_one = AsyncMock()

        with patch.object(profile_service, "get_registrations_collection", return_value=collection):
            result = await profile_service.update_seller_store_name(
                seller_id,
                SellerStoreNameUpdate(store_name="ferretería"),
            )

        self.assertEqual(result.store_name, "Ferretería")
        collection.update_one.assert_not_awaited()

    async def test_rejects_duplicate_store_name(self) -> None:
        from app.services import seller_profile as profile_service

        seller_id = str(ObjectId())
        doc = self._seller_doc(seller_id)

        collection = AsyncMock()
        collection.find_one = AsyncMock(side_effect=[doc, {"_id": ObjectId()}])

        with patch.object(profile_service, "get_registrations_collection", return_value=collection):
            with self.assertRaises(HTTPException) as ctx:
                await profile_service.update_seller_store_name(
                    seller_id,
                    SellerStoreNameUpdate(store_name="Panadería Central"),
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("ya está ocupado", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
