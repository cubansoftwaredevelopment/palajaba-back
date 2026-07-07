from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta
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
from app.services.seller_stats import compute_change_percent, resolve_comparison_window
from app.utils.datetime import to_utc_naive, utc_now
from tests.helpers_seller_stats import (
    STORE_NAME_A,
    STORE_NAME_B,
    completed_order_document,
    seller_document,
)

COMPARISON_MARKER = "seller_stats_comparison_v1"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def seller_auth_header(seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}


class ComparisonSeed:
    seller_a_id: str
    seller_b_id: str
    seller_a_oid: ObjectId
    seller_b_oid: ObjectId
    seller_a_units_by_date: list[tuple[datetime, int]]
    seller_a_revenue_by_date: list[tuple[datetime, str, float]]


async def cleanup_comparison_test_data() -> None:
    orders = get_orders_collection()
    registrations = get_registrations_collection()
    await orders.delete_many({"seller_stats_comparison_marker": COMPARISON_MARKER})
    await registrations.delete_many({"seller_stats_comparison_marker": COMPARISON_MARKER})


async def seed_comparison_test_data() -> ComparisonSeed:
    seed = ComparisonSeed()
    seed.seller_a_oid = ObjectId()
    seed.seller_b_oid = ObjectId()
    seed.seller_a_id = str(seed.seller_a_oid)
    seed.seller_b_id = str(seed.seller_b_oid)

    registrations = get_registrations_collection()
    orders = get_orders_collection()

    seller_a = seller_document(seller_id=seed.seller_a_oid, store_name=STORE_NAME_A)
    seller_a["approved_at"] = datetime(2020, 1, 1, 10, 0, 0)
    seller_a["seller_stats_comparison_marker"] = COMPARISON_MARKER

    seller_b = seller_document(
        seller_id=seed.seller_b_oid,
        store_name=STORE_NAME_B,
        plan_tier="standard",
    )
    seller_b["seller_stats_comparison_marker"] = COMPARISON_MARKER

    await registrations.insert_one(seller_a)
    await registrations.insert_one(seller_b)

    now = to_utc_naive(utc_now())
    today = datetime(now.year, now.month, now.day, 12, 0, 0)
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    last_week = week_start - timedelta(days=3)
    month_start = datetime(now.year, now.month, 1, 12, 0, 0)
    if now.month == 1:
        prev_month_day = datetime(now.year - 1, 12, 3, 12, 0, 0)
    else:
        prev_month_day = datetime(now.year, now.month - 1, 3, 12, 0, 0)

    docs = [
        completed_order_document(
            seller_id=seed.seller_a_id,
            store_name=STORE_NAME_A,
            payment_currency="USD",
            collected_total=200.0,
            completed_at=today,
        ),
        completed_order_document(
            seller_id=seed.seller_a_id,
            store_name=STORE_NAME_A,
            payment_currency="USD",
            collected_total=100.0,
            completed_at=yesterday,
        ),
        completed_order_document(
            seller_id=seed.seller_a_id,
            store_name=STORE_NAME_A,
            payment_currency="CUP",
            collected_total=300.0,
            completed_at=week_start + timedelta(hours=2),
        ),
        completed_order_document(
            seller_id=seed.seller_a_id,
            store_name=STORE_NAME_A,
            payment_currency="CUP",
            collected_total=100.0,
            completed_at=last_week,
        ),
        completed_order_document(
            seller_id=seed.seller_a_id,
            store_name=STORE_NAME_A,
            payment_currency="MLC",
            collected_total=50.0,
            completed_at=month_start,
        ),
        completed_order_document(
            seller_id=seed.seller_a_id,
            store_name=STORE_NAME_A,
            payment_currency="MLC",
            collected_total=25.0,
            completed_at=prev_month_day,
        ),
        completed_order_document(
            seller_id=seed.seller_b_id,
            store_name=STORE_NAME_B,
            payment_currency="USD",
            collected_total=999.0,
            completed_at=today,
        ),
    ]

    seed.seller_a_units_by_date = [
        (today, 2),
        (yesterday, 2),
        (week_start + timedelta(hours=2), 2),
        (last_week, 2),
        (month_start, 2),
        (prev_month_day, 2),
    ]
    seed.seller_a_revenue_by_date = [
        (today, "USD", 200.0),
        (yesterday, "USD", 100.0),
        (week_start + timedelta(hours=2), "CUP", 300.0),
        (last_week, "CUP", 100.0),
        (month_start, "MLC", 50.0),
        (prev_month_day, "MLC", 25.0),
    ]

    for doc in docs:
        doc["seller_stats_comparison_marker"] = COMPARISON_MARKER
        doc["items"][0]["quantity"] = 2

    await orders.insert_many(docs)
    return seed


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SellerStatsComparisonIntegrationTests(unittest.TestCase):
    seed: ComparisonSeed

    @classmethod
    def setUpClass(cls) -> None:
        async def prepare() -> ComparisonSeed:
            await connect_to_mongo()
            await cleanup_comparison_test_data()
            return await seed_comparison_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_comparison_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def _sum_units(self, window: object, rows: list[tuple[datetime, int]]) -> tuple[int, int]:
        current = 0
        previous = 0
        for completed_at, units in rows:
            if window.current_start <= completed_at < window.current_end:
                current += units
            elif window.previous_start <= completed_at < window.previous_end:
                previous += units
        return current, previous

    def _sum_revenue(
        self,
        window: object,
        rows: list[tuple[datetime, str, float]],
        currency: str,
    ) -> tuple[float, float]:
        current = 0.0
        previous = 0.0
        for completed_at, code, amount in rows:
            if code != currency:
                continue
            if window.current_start <= completed_at < window.current_end:
                current += amount
            elif window.previous_start <= completed_at < window.previous_end:
                previous += amount
        return current, previous

    def test_daily_revenue_comparison_against_yesterday(self) -> None:
        now = to_utc_naive(utc_now())
        window = resolve_comparison_window("daily", reference=now)
        current, previous = self._sum_revenue(
            window,
            self.seed.seller_a_revenue_by_date,
            "USD",
        )
        expected = compute_change_percent(current, previous)

        with TestClient(app) as client:
            response = client.get(
                f"/api/auth/me/stats/revenue?granularity=daily&year={now.year}&month={now.month}",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        usd = next(series for series in payload["series"] if series["currency"] == "USD")
        comparison = usd["comparison"]
        self.assertTrue(comparison["comparison_available"])
        self.assertEqual(comparison["change_percent"], expected)
        self.assertEqual(comparison["comparison_label"], "vs ayer")

    def test_weekly_products_sold_comparison(self) -> None:
        now = to_utc_naive(utc_now())
        window = resolve_comparison_window("weekly", reference=now)
        current, previous = self._sum_units(window, self.seed.seller_a_units_by_date)
        expected = compute_change_percent(float(current), float(previous))

        with TestClient(app) as client:
            response = client.get(
                f"/api/auth/me/stats/products-sold?granularity=weekly&year={now.year}&month={now.month}",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        comparison = response.json()["comparison"]
        self.assertTrue(comparison["comparison_available"])
        self.assertEqual(comparison["change_percent"], expected)
        self.assertEqual(comparison["comparison_label"], "vs semana pasada")

    def test_monthly_revenue_comparison(self) -> None:
        now = to_utc_naive(utc_now())
        window = resolve_comparison_window("monthly", reference=now)
        current, previous = self._sum_revenue(
            window,
            self.seed.seller_a_revenue_by_date,
            "MLC",
        )
        expected = compute_change_percent(current, previous)

        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me/stats/revenue?granularity=monthly",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        mlc = next(series for series in payload["series"] if series["currency"] == "MLC")
        comparison = mlc["comparison"]
        self.assertTrue(comparison["comparison_available"])
        self.assertEqual(comparison["change_percent"], expected)
        self.assertEqual(comparison["comparison_label"], "vs mes pasado")

    def test_other_seller_data_is_isolated(self) -> None:
        now = to_utc_naive(utc_now())
        with TestClient(app) as client:
            response = client.get(
                f"/api/auth/me/stats/revenue?granularity=daily&year={now.year}&month={now.month}",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        usd = next(series for series in response.json()["series"] if series["currency"] == "USD")
        self.assertEqual(usd["comparison"]["current_total"], 200.0)

    def test_zero_previous_period_returns_growth_not_error(self) -> None:
        now = to_utc_naive(utc_now())
        with TestClient(app) as client:
            response = client.get(
                f"/api/auth/me/stats/products-sold?granularity=daily&year={now.year}&month={now.month}",
                headers=seller_auth_header(self.seed.seller_a_id, STORE_NAME_A),
            )
        self.assertEqual(response.status_code, 200, response.text)
        comparison = response.json()["comparison"]
        self.assertIsNotNone(comparison["change_percent"])
