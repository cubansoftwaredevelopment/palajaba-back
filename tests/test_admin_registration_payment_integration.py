from __future__ import annotations

import asyncio
import os
import unittest
from datetime import timedelta
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import HTTPException
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import close_mongo_connection, connect_to_mongo, get_registrations_collection
from app.main import app
from app.security import create_admin_token
from app.services import registrations as registration_service
from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers_admin_registration_payment import (
    MARKER,
    approved_registration_document,
    expired_registration_document,
    pending_registration_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


class PaymentTestSeed:
    pending_id: ObjectId
    expired_id: ObjectId
    approved_id: ObjectId


async def cleanup_payment_test_data() -> None:
    await get_registrations_collection().delete_many({MARKER: True})


async def seed_payment_test_data() -> PaymentTestSeed:
    seed = PaymentTestSeed()
    seed.pending_id = ObjectId()
    seed.expired_id = ObjectId()
    seed.approved_id = ObjectId()

    registrations = get_registrations_collection()
    await registrations.insert_one(pending_registration_document(registration_id=seed.pending_id))
    await registrations.insert_one(expired_registration_document(registration_id=seed.expired_id))
    await registrations.insert_one(approved_registration_document(registration_id=seed.approved_id))
    return seed


def admin_auth_header() -> dict[str, str]:
    token = create_admin_token(username="test-admin", admin_id=str(ObjectId()))
    return {"Authorization": f"Bearer {token}"}


def future_subscription_end_date() -> str:
    return (to_utc_naive(utc_now()) + timedelta(days=30)).strftime("%Y-%m-%d")


async def insert_registration_document(document: dict) -> None:
    await connect_to_mongo()
    await get_registrations_collection().insert_one(document)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminRegistrationPaymentServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    seed: PaymentTestSeed

    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_payment_test_data()
        self.seed = await seed_payment_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_payment_test_data()
        await close_mongo_connection()

    async def test_approve_free_registration_persists_zero_payment(self) -> None:
        ends_at = to_utc_naive(utc_now()) + timedelta(days=30)
        result = await registration_service.approve_registration(
            str(self.seed.pending_id),
            ends_at,
            0,
        )

        self.assertEqual(result.status, "approved")
        self.assertEqual(result.payment_amount_cup, 0)

        doc = await get_registrations_collection().find_one({"_id": self.seed.pending_id})
        assert doc is not None
        self.assertEqual(doc["status"], "approved")
        self.assertEqual(doc["payment_amount_cup"], 0)
        self.assertIsNotNone(doc["subscription_ends_at"])

    async def test_renew_free_registration_persists_zero_payment(self) -> None:
        ends_at = to_utc_naive(utc_now()) + timedelta(days=365)
        result = await registration_service.renew_registration(
            str(self.seed.expired_id),
            ends_at,
            0,
        )

        self.assertEqual(result.status, "approved")
        self.assertEqual(result.payment_amount_cup, 0)

        doc = await get_registrations_collection().find_one({"_id": self.seed.expired_id})
        assert doc is not None
        self.assertEqual(doc["status"], "approved")
        self.assertEqual(doc["payment_amount_cup"], 0)

    async def test_update_payment_to_zero(self) -> None:
        result = await registration_service.update_payment_amount(str(self.seed.approved_id), 0)

        self.assertEqual(result.payment_amount_cup, 0)

        doc = await get_registrations_collection().find_one({"_id": self.seed.approved_id})
        assert doc is not None
        self.assertEqual(doc["payment_amount_cup"], 0)

    async def test_approve_rejects_negative_payment(self) -> None:
        pending_id = ObjectId()
        await get_registrations_collection().insert_one(
            pending_registration_document(registration_id=pending_id)
        )
        ends_at = to_utc_naive(utc_now()) + timedelta(days=30)

        with self.assertRaises(HTTPException) as ctx:
            await registration_service.approve_registration(str(pending_id), ends_at, -5)

        self.assertEqual(ctx.exception.status_code, 400)
        doc = await get_registrations_collection().find_one({"_id": pending_id})
        assert doc is not None
        self.assertEqual(doc["status"], "pending")


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminRegistrationPaymentApiIntegrationTests(unittest.TestCase):
    seed: PaymentTestSeed

    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> PaymentTestSeed:
            await connect_to_mongo()
            await cleanup_payment_test_data()
            return await seed_payment_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_payment_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_http_approve_with_zero_payment(self) -> None:
        pending_id = ObjectId()
        asyncio.run(insert_registration_document(pending_registration_document(registration_id=pending_id)))

        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/registrations/{pending_id}/approve",
                params={
                    "payment_amount_cup": 0,
                    "subscription_ends_at": future_subscription_end_date(),
                },
                headers=admin_auth_header(),
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["payment_amount_cup"], 0)

    def test_http_renew_with_zero_payment(self) -> None:
        expired_id = ObjectId()
        asyncio.run(insert_registration_document(expired_registration_document(registration_id=expired_id)))

        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/registrations/{expired_id}/renew",
                params={
                    "payment_amount_cup": 0,
                    "subscription_ends_at": future_subscription_end_date(),
                },
                headers=admin_auth_header(),
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["payment_amount_cup"], 0)

    def test_http_update_payment_with_zero(self) -> None:
        approved_id = ObjectId()
        asyncio.run(
            insert_registration_document(
                approved_registration_document(
                    registration_id=approved_id,
                    payment_amount_cup=7500,
                )
            )
        )

        with TestClient(app) as client:
            response = client.patch(
                f"/api/admin/registrations/{approved_id}/payment",
                params={"payment_amount_cup": 0},
                headers=admin_auth_header(),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["payment_amount_cup"], 0)

    def test_http_approve_negative_payment_returns_422(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/registrations/{self.seed.pending_id}/approve",
                params={
                    "payment_amount_cup": -1,
                    "subscription_ends_at": future_subscription_end_date(),
                },
                headers=admin_auth_header(),
            )

        self.assertEqual(response.status_code, 422, response.text)

    def test_http_approve_without_token_returns_401(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/registrations/{self.seed.pending_id}/approve",
                params={
                    "payment_amount_cup": 0,
                    "subscription_ends_at": future_subscription_end_date(),
                },
            )

        self.assertEqual(response.status_code, 401, response.text)

    def test_http_register_and_approve_free_end_to_end(self) -> None:
        suffix = str(ObjectId())[-8:]
        transfer_id = f"TEST-E2E-{suffix}"
        phone = f"{int(suffix, 16) % 100000000:08d}"
        store_name = f"TEST E2E Free {suffix}"

        with TestClient(app) as client:
            register_response = client.post(
                "/api/register",
                json={
                    "transfer_id": transfer_id,
                    "store_name": store_name,
                    "phone": phone,
                    "password": "TestPay2026!",
                    "billing_period": "monthly",
                    "plan_tier": "standard",
                },
            )
            self.assertEqual(register_response.status_code, 201, register_response.text)
            registration_id = register_response.json()["id"]

            approve_response = client.post(
                f"/api/admin/registrations/{registration_id}/approve",
                params={
                    "payment_amount_cup": 0,
                    "subscription_ends_at": future_subscription_end_date(),
                },
                headers=admin_auth_header(),
            )

        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        payload = approve_response.json()
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["payment_amount_cup"], 0)
        self.assertEqual(payload["store_name"], store_name)


if __name__ == "__main__":
    unittest.main()
