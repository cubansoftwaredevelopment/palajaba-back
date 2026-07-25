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

from app.database import (  # noqa: E402
    close_mongo_connection,
    connect_to_mongo,
    get_orders_collection,
    get_registrations_collection,
)
from app.main import app  # noqa: E402
from app.security import create_admin_token  # noqa: E402
from app.services import admin_order_stats as order_stats_service  # noqa: E402
from app.utils.datetime import to_utc_naive, utc_now  # noqa: E402
from tests.helpers_seller_stats import completed_order_document, seller_document  # noqa: E402

MARKER = "admin_order_stats_test_v1"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def admin_auth_header() -> dict[str, str]:
    token = create_admin_token(username="orders-admin", admin_id=str(ObjectId()))
    return {"Authorization": f"Bearer {token}"}


async def cleanup() -> None:
    await get_orders_collection().delete_many({"admin_order_stats_marker": MARKER})
    await get_registrations_collection().delete_many({"admin_order_stats_marker": MARKER})


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminOrderStatsServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup()

        self.seller_a = ObjectId()
        self.seller_b = ObjectId()
        self.seller_c = ObjectId()

        seller_a = seller_document(seller_id=self.seller_a, store_name="Alpha Pedidos")
        seller_a["admin_order_stats_marker"] = MARKER
        seller_a["business_area"] = {
            "province_id": "la-habana",
            "province_name": "La Habana",
            "municipality_id": "playa",
            "municipality_name": "Playa",
        }

        seller_b = seller_document(seller_id=self.seller_b, store_name="Beta Pedidos")
        seller_b["admin_order_stats_marker"] = MARKER
        seller_b["business_area"] = {
            "province_id": "matanzas",
            "province_name": "Matanzas",
            "municipality_id": "matanzas",
            "municipality_name": "Matanzas",
        }

        seller_c = seller_document(seller_id=self.seller_c, store_name="Gamma Pedidos")
        seller_c["admin_order_stats_marker"] = MARKER
        seller_c["business_area"] = {
            "province_id": "la-habana",
            "province_name": "La Habana",
            "municipality_id": "centro-habana",
            "municipality_name": "Centro Habana",
        }

        await get_registrations_collection().insert_many([seller_a, seller_b, seller_c])

        now = to_utc_naive(utc_now())
        today = datetime(now.year, now.month, now.day, 14, 0, 0)

        docs = []
        for _ in range(3):
            doc = completed_order_document(
                seller_id=str(self.seller_a),
                store_name="Alpha Pedidos",
                payment_currency="CUP",
                collected_total=100,
                completed_at=today,
            )
            doc["admin_order_stats_marker"] = MARKER
            docs.append(doc)

        for _ in range(2):
            doc = completed_order_document(
                seller_id=str(self.seller_b),
                store_name="Beta Pedidos",
                payment_currency="CUP",
                collected_total=80,
                completed_at=today,
            )
            doc["admin_order_stats_marker"] = MARKER
            docs.append(doc)

        doc = completed_order_document(
            seller_id=str(self.seller_c),
            store_name="Gamma Pedidos",
            payment_currency="CUP",
            collected_total=50,
            completed_at=today - timedelta(days=1),
        )
        doc["admin_order_stats_marker"] = MARKER
        docs.append(doc)

        await get_orders_collection().insert_many(docs)

    async def asyncTearDown(self) -> None:
        await cleanup()
        await close_mongo_connection()

    async def test_top_businesses_daily(self) -> None:
        result = await order_stats_service.get_top_businesses(granularity="daily")
        self.assertEqual(result.granularity, "daily")
        self.assertGreaterEqual(result.total_orders, 5)
        self.assertGreaterEqual(len(result.businesses), 2)
        self.assertEqual(result.businesses[0].store_name, "Alpha Pedidos")
        self.assertEqual(result.businesses[0].count, 3)
        self.assertEqual(result.businesses[1].store_name, "Beta Pedidos")
        self.assertEqual(result.businesses[1].count, 2)

    async def test_orders_by_location_monthly(self) -> None:
        result = await order_stats_service.get_orders_by_location(granularity="monthly")
        self.assertGreaterEqual(result.total_orders, 6)
        province_ids = {item.province_id for item in result.provinces}
        self.assertIn("la-habana", province_ids)
        self.assertIn("matanzas", province_ids)
        muni_ids = {item.municipality_id for item in result.municipalities}
        self.assertIn("playa", muni_ids)

    async def test_orders_chart_daily(self) -> None:
        now = to_utc_naive(utc_now())
        chart = await order_stats_service.get_orders_chart(
            granularity="daily",
            year=now.year,
            month=now.month,
        )
        self.assertEqual(chart.granularity, "daily")
        self.assertGreaterEqual(chart.total_orders, 6)
        self.assertTrue(any(point.count > 0 for point in chart.points))


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminOrderStatsApiIntegrationTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_admin_orders_endpoints(self) -> None:
        headers = admin_auth_header()
        with TestClient(app) as client:
            chart = client.get(
                "/api/admin/stats/orders?granularity=daily",
                headers=headers,
            )
            self.assertEqual(chart.status_code, 200, chart.text)
            self.assertIn("points", chart.json())

            top = client.get(
                "/api/admin/stats/orders/top-businesses?granularity=monthly",
                headers=headers,
            )
            self.assertEqual(top.status_code, 200, top.text)
            self.assertIn("businesses", top.json())

            locations = client.get(
                "/api/admin/stats/orders/locations?granularity=weekly",
                headers=headers,
            )
            self.assertEqual(locations.status_code, 200, locations.text)
            self.assertIn("provinces", locations.json())
            self.assertIn("municipalities", locations.json())


if __name__ == "__main__":
    unittest.main()
