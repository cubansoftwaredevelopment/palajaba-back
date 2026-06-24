from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import HTTPException
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_discount_codes_collection,
    get_registrations_collection,
)
from app.main import app
from app.schemas.discount_code import DiscountCodeUpdate
from app.security import create_admin_token
from app.services import discount_codes as discount_codes_service

TEST_DISCOUNT_CODES = ["TEST20", "INACTIVE50", "SAVE25", "EDITME", "PUBLIC10", "FRIEND30"]


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def admin_auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_admin_token(username='test-admin', admin_id=str(ObjectId()))}"}


async def cleanup_discount_code_test_data() -> None:
    await get_discount_codes_collection().delete_many({"code": {"$in": TEST_DISCOUNT_CODES}})
    await get_registrations_collection().delete_many({"transfer_id": {"$regex": "^TEST-DISC-"}})


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class DiscountCodeServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_discount_code_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_discount_code_test_data()
        await close_mongo_connection()

    async def test_has_active_discount_codes_reflects_active_entries(self) -> None:
        self.assertFalse(await discount_codes_service.has_active_discount_codes())
        await discount_codes_service.create_discount_code(code="TEST20", percent_off=20, is_active=True)
        self.assertTrue(await discount_codes_service.has_active_discount_codes())

    async def test_inactive_code_is_not_available_for_validation(self) -> None:
        created = await discount_codes_service.create_discount_code(
            code="INACTIVE50",
            percent_off=50,
            is_active=False,
        )
        self.assertFalse(await discount_codes_service.has_active_discount_codes())
        with self.assertRaises(HTTPException) as ctx:
            await discount_codes_service.validate_discount_code(
                created.code,
                plan_tier="standard",
                billing_period="monthly",
            )
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("app.services.discount_codes.plan_price_cup", return_value=1000)
    async def test_validate_discount_code_returns_discounted_amount(self, _mock_price) -> None:
        await discount_codes_service.create_discount_code(code="SAVE25", percent_off=25, is_active=True)
        result = await discount_codes_service.validate_discount_code(
            "save25",
            plan_tier="standard",
            billing_period="monthly",
        )
        self.assertEqual(result.code, "SAVE25")
        self.assertEqual(result.percent_off, 25)
        self.assertEqual(result.original_amount_cup, 1000)
        self.assertEqual(result.discounted_amount_cup, 750)

    @patch("app.services.discount_codes.plan_price_cup", return_value=2000)
    async def test_update_and_delete_discount_code(self, _mock_price) -> None:
        created = await discount_codes_service.create_discount_code(code="EDITME", percent_off=10, is_active=True)
        updated = await discount_codes_service.update_discount_code(
            created.id,
            DiscountCodeUpdate(percent_off=40, is_active=False),
        )
        self.assertEqual(updated.percent_off, 40)
        self.assertFalse(updated.is_active)

        deleted = await discount_codes_service.delete_discount_code(created.id)
        self.assertEqual(deleted.id, created.id)
        codes = await discount_codes_service.list_discount_codes()
        self.assertEqual(codes, [])


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class DiscountCodeApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        async def prepare() -> None:
            await connect_to_mongo()
            await cleanup_discount_code_test_data()

        asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_discount_code_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_public_availability_endpoint(self) -> None:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/admin/discount-codes",
                headers=admin_auth_header(),
                json={"code": "PUBLIC10", "percent_off": 10, "is_active": True},
            )
            self.assertEqual(create_response.status_code, 201, create_response.text)
            code_id = create_response.json()["id"]

            available = client.get("/api/platform/discount-codes/availability")
            self.assertEqual(available.status_code, 200, available.text)
            self.assertTrue(available.json()["available"])

            invalid = client.post(
                "/api/platform/discount-codes/validate",
                json={"code": "NOPE", "plan_tier": "standard", "billing_period": "monthly"},
            )
            self.assertEqual(invalid.status_code, 404, invalid.text)

            delete_response = client.delete(
                f"/api/admin/discount-codes/{code_id}",
                headers=admin_auth_header(),
            )
            self.assertEqual(delete_response.status_code, 200, delete_response.text)

            unavailable = client.get("/api/platform/discount-codes/availability")
            self.assertFalse(unavailable.json()["available"])

    @patch("app.services.discount_codes.plan_price_cup", return_value=1000)
    def test_admin_crud_and_register_with_discount_code(self, _mock_price) -> None:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/admin/discount-codes",
                headers=admin_auth_header(),
                json={"code": "FRIEND30", "percent_off": 30, "is_active": True},
            )
            self.assertEqual(create_response.status_code, 201, create_response.text)
            created = create_response.json()

            list_response = client.get("/api/admin/discount-codes", headers=admin_auth_header())
            self.assertEqual(list_response.status_code, 200, list_response.text)
            self.assertTrue(any(row["code"] == "FRIEND30" for row in list_response.json()))

            validate_response = client.post(
                "/api/platform/discount-codes/validate",
                json={"code": "friend30", "plan_tier": "premium", "billing_period": "yearly"},
            )
            self.assertEqual(validate_response.status_code, 200, validate_response.text)
            self.assertEqual(validate_response.json()["discounted_amount_cup"], 700)

            suffix = str(ObjectId())[-8:]
            register_response = client.post(
                "/api/register",
                json={
                    "transfer_id": f"TEST-DISC-{suffix}",
                    "store_name": f"TEST Discount Store {suffix}",
                    "phone": f"{int(suffix, 16) % 100000000:08d}",
                    "password": "TestDisc2026!",
                    "billing_period": "monthly",
                    "plan_tier": "standard",
                    "discount_code": "FRIEND30",
                },
            )
            self.assertEqual(register_response.status_code, 201, register_response.text)
            registration_id = register_response.json()["id"]

            detail_response = client.get(
                f"/api/admin/registrations/{registration_id}",
                headers=admin_auth_header(),
            )
            self.assertEqual(detail_response.status_code, 200, detail_response.text)
            detail = detail_response.json()
            self.assertEqual(detail["discount_code"], "FRIEND30")
            self.assertEqual(detail["discount_percent"], 30)
            self.assertEqual(detail["expected_payment_cup"], 700)

            delete_response = client.delete(
                f"/api/admin/discount-codes/{created['id']}",
                headers=admin_auth_header(),
            )
            self.assertEqual(delete_response.status_code, 200, delete_response.text)

            unavailable = client.get("/api/platform/discount-codes/availability")
            self.assertFalse(unavailable.json()["available"])


if __name__ == "__main__":
    unittest.main()
