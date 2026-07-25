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
    get_marketplace_visits_collection,
)
from app.main import app  # noqa: E402
from app.security import create_admin_token  # noqa: E402
from app.services import marketplace_traffic as traffic_service  # noqa: E402
from app.services.cuba_time import cuba_date_str, cuba_hour, cuba_weekday  # noqa: E402
from app.utils.datetime import to_utc_naive, utc_now  # noqa: E402

MARKER = "marketplace_traffic_test_v1"


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


def admin_auth_header() -> dict[str, str]:
    token = create_admin_token(username="traffic-admin", admin_id=str(ObjectId()))
    return {"Authorization": f"Bearer {token}"}


async def cleanup_traffic_test_data() -> None:
    await get_marketplace_visits_collection().delete_many({"test_marker": MARKER})


def visit_document(
    *,
    session_id: str,
    viewed_at: datetime,
    province_id: str = "la-habana",
    province_name: str = "La Habana",
    municipality_id: str = "plaza-de-la-revolucion",
    municipality_name: str = "Plaza de la Revolución",
) -> dict:
    viewed_at = to_utc_naive(viewed_at)
    return {
        "session_id": session_id,
        "page": "marketplace",
        "province_id": province_id,
        "province_name": province_name,
        "municipality_id": municipality_id,
        "municipality_name": municipality_name,
        "viewed_at": viewed_at,
        "cuba_date": cuba_date_str(viewed_at),
        "cuba_hour": cuba_hour(viewed_at),
        "cuba_weekday": cuba_weekday(viewed_at),
        "test_marker": MARKER,
    }


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class MarketplaceTrafficServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await traffic_service.ensure_marketplace_visit_indexes()
        await cleanup_traffic_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_traffic_test_data()
        await close_mongo_connection()

    async def test_record_visit_and_dedupe_same_session_day(self) -> None:
        from app.schemas.marketplace_traffic import MarketplaceVisitRequest

        session_id = f"sess_integration_{ObjectId()}"
        payload = MarketplaceVisitRequest(
            session_id=session_id,
            province_id="la-habana",
            municipality_id="plaza-de-la-revolucion",
        )
        first = await traffic_service.record_marketplace_visit(payload)
        second = await traffic_service.record_marketplace_visit(payload)

        self.assertTrue(first.recorded)
        self.assertFalse(first.duplicate)
        self.assertFalse(second.recorded)
        self.assertTrue(second.duplicate)

        count = await get_marketplace_visits_collection().count_documents(
            {"session_id": session_id}
        )
        self.assertEqual(count, 1)

        await get_marketplace_visits_collection().update_many(
            {"session_id": session_id},
            {"$set": {"test_marker": MARKER}},
        )

    async def test_traffic_chart_and_patterns(self) -> None:
        now = to_utc_naive(utc_now())
        today = datetime(now.year, now.month, now.day, 16, 0, 0)
        yesterday = today - timedelta(days=1)

        await get_marketplace_visits_collection().insert_many(
            [
                visit_document(session_id=f"chart_a_{ObjectId()}", viewed_at=today),
                visit_document(
                    session_id=f"chart_b_{ObjectId()}",
                    viewed_at=today.replace(hour=18),
                    municipality_id="centro-habana",
                    municipality_name="Centro Habana",
                ),
                visit_document(session_id=f"chart_c_{ObjectId()}", viewed_at=yesterday),
            ]
        )

        chart = await traffic_service.get_traffic_chart(
            granularity="daily",
            year=now.year,
            month=now.month,
        )
        self.assertGreaterEqual(chart.total_visits, 3)
        self.assertEqual(chart.granularity, "daily")
        self.assertIsNotNone(chart.comparison)

        locations = await traffic_service.get_traffic_by_location(
            year=now.year,
            month=now.month,
        )
        self.assertGreaterEqual(locations.total_visits, 3)
        self.assertTrue(any(item.province_id == "la-habana" for item in locations.provinces))
        self.assertTrue(
            any(item.municipality_id == "plaza-de-la-revolucion" for item in locations.municipalities)
        )

        patterns = await traffic_service.get_traffic_patterns(year=now.year, month=now.month)
        self.assertEqual(len(patterns.by_hour), 24)
        self.assertEqual(len(patterns.by_weekday), 7)
        self.assertGreaterEqual(patterns.total_visits, 3)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class MarketplaceTrafficApiIntegrationTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_traffic_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_post_visit_and_admin_endpoints(self) -> None:
        session_id = f"api_sess_{ObjectId()}"

        with TestClient(app) as client:
            response = client.post(
                "/api/marketplace/visits",
                json={
                    "session_id": session_id,
                    "page": "marketplace",
                    "province_id": "matanzas",
                    "municipality_id": "matanzas",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["recorded"])

            dup = client.post(
                "/api/marketplace/visits",
                json={
                    "session_id": session_id,
                    "page": "marketplace",
                    "province_id": "matanzas",
                    "municipality_id": "matanzas",
                },
            )
            self.assertEqual(dup.status_code, 200)
            self.assertTrue(dup.json()["duplicate"])

            headers = admin_auth_header()
            chart = client.get("/api/admin/stats/traffic?granularity=daily", headers=headers)
            self.assertEqual(chart.status_code, 200, chart.text)
            self.assertIn("points", chart.json())

            locations = client.get("/api/admin/stats/traffic/locations", headers=headers)
            self.assertEqual(locations.status_code, 200, locations.text)

            patterns = client.get("/api/admin/stats/traffic/patterns", headers=headers)
            self.assertEqual(patterns.status_code, 200, patterns.text)
            self.assertEqual(len(patterns.json()["by_hour"]), 24)

            summary = client.get("/api/admin/stats/summary", headers=headers)
            self.assertEqual(summary.status_code, 200)
            self.assertIn("marketplace_visits", summary.json())

        async def _mark() -> None:
            await connect_to_mongo()
            await get_marketplace_visits_collection().update_one(
                {"session_id": session_id},
                {"$set": {"test_marker": MARKER}},
            )
            await close_mongo_connection()

        asyncio.run(_mark())

    def test_rejects_invalid_province(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/marketplace/visits",
                json={
                    "session_id": "sess_bad_province_01",
                    "province_id": "no-existe",
                    "municipality_id": "tampoco",
                },
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
