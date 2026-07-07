from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_orders_collection,
    get_registrations_collection,
)
from app.main import app
from app.security import create_seller_token
from tests.helpers_seller_stats import (
    MARKER,
    STORE_NAME_A,
    STORE_NAME_B,
    completed_order_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def seller_auth_header(seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}


class RevenueTotalsSeed:
    seller_a_id: str
    seller_b_id: str
    seller_a_oid: ObjectId
    seller_b_oid: ObjectId


async def cleanup_revenue_totals_test_data() -> None:
    orders = get_orders_collection()
    registrations = get_registrations_collection()
    await orders.delete_many({"seller_stats_revenue_totals_marker": MARKER})
    await registrations.delete_many({"seller_stats_revenue_totals_marker": MARKER})


async def seed_revenue_totals_test_data() -> RevenueTotalsSeed:
    seed = RevenueTotalsSeed()
    seed.seller_a_oid = ObjectId()
    seed.seller_b_oid = ObjectId()
    seed.seller_a_id = str(seed.seller_a_oid)
    seed.seller_b_id = str(seed.seller_b_oid)

    registrations = get_registrations_collection()
    orders = get_orders_collection()

    await registrations.insert_one(seller_document(seller_id=seed.seller_a_oid, store_name=STORE_NAME_A))
    await registrations.insert_one(
        seller_document(
            seller_id=seed.seller_b_oid,
            store_name=STORE_NAME_B,
            plan_tier="standard",
        )
    )

    march_2026 = datetime(2026, 3, 15, 12, 0, 0)
    april_2026 = datetime(2026, 4, 10, 12, 0, 0)

    await orders.insert_many(
        [
            completed_order_document(
                seller_id=seed.seller_a_id,
                store_name=STORE_NAME_A,
                payment_currency="USD",
                collected_total=100.0,
                completed_at=march_2026,
            ),
            completed_order_document(
                seller_id=seed.seller_a_id,
                store_name=STORE_NAME_A,
                payment_currency="CUP",
                collected_total=500.0,
                completed_at=march_2026,
                with_delivery=True,
            ),
            completed_order_document(
                seller_id=seed.seller_a_id,
                store_name=STORE_NAME_A,
                payment_currency="USD",
                collected_total=40.0,
                completed_at=april_2026,
            ),
            completed_order_document(
                seller_id=seed.seller_b_id,
                store_name=STORE_NAME_B,
                payment_currency="USD",
                collected_total=999.0,
                completed_at=march_2026,
            ),
        ]
    )
    return seed


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SellerRevenueTotalsIntegrationTests(unittest.TestCase):
    seed: RevenueTotalsSeed

    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> RevenueTotalsSeed:
            await connect_to_mongo()
            await cleanup_revenue_totals_test_data()
            return await seed_revenue_totals_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_revenue_totals_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_premium_seller_gets_monthly_totals_without_delivery(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me/stats/revenue-totals?year=2026&month=3",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["year"], 2026)
        self.assertEqual(payload["month"], 3)
        self.assertEqual(payload["orders_count"], 2)
        by_currency = {item["currency"]: item["amount"] for item in payload["totals"]}
        self.assertEqual(by_currency["USD"], 100.0)
        self.assertEqual(by_currency["CUP"], 500.0)
        self.assertEqual(by_currency["MLC"], 0.0)
        self.assertEqual(by_currency["EUR"], 0.0)

    def test_month_filter_excludes_other_months(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me/stats/revenue-totals?year=2026&month=4",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        by_currency = {item["currency"]: item["amount"] for item in payload["totals"]}
        self.assertEqual(payload["orders_count"], 1)
        self.assertEqual(by_currency["USD"], 40.0)
        self.assertEqual(by_currency["CUP"], 0.0)

    def test_seller_cannot_see_other_seller_totals(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me/stats/revenue-totals?year=2026&month=3",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        by_currency = {item["currency"]: item["amount"] for item in response.json()["totals"]}
        self.assertNotEqual(by_currency["USD"], 999.0)

    def test_standard_plan_returns_forbidden(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me/stats/revenue-totals?year=2026&month=3",
                headers=seller_auth_header(self.seed.seller_b_id, STORE_NAME_B),
            )
        self.assertEqual(response.status_code, 403)

    def test_empty_month_returns_zero_totals(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me/stats/revenue-totals?year=2026&month=1",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["orders_count"], 0)
        self.assertTrue(all(item["amount"] == 0.0 for item in payload["totals"]))
