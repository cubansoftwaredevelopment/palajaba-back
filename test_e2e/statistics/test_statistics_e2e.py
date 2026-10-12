"""Recorrido de estadísticas admin: de la API a Mongo y de vuelta a las gráficas."""

from __future__ import annotations

import unittest

from bson import ObjectId

from test_e2e.statistics.fixtures.constants import (
    CUP_COLLECTED,
    ISOLATED_DAY,
    LIVE_LAT,
    LIVE_LNG,
    PAST_LAT,
    PAST_LNG,
    PAYMENT_CUP,
    SOLD_LEAD_NAME,
    SOLD_SECOND_NAME,
    WEB_LAT,
    WEB_LNG,
)
from test_e2e.statistics.fixtures.history import store_name
from test_e2e.statistics.fixtures.presence import (
    anonymous_presence,
    logged_out_presence,
    seller_presence,
    tracked_id,
    visit_payload,
    web_buyer_presence,
)
from test_e2e.statistics.utils import (
    cleanup,
    count_for,
    day_params,
    device_day,
    same_point,
    seed_history,
    seed_past_device_day,
    summary_params,
    today,
)
from test_e2e.utils.api import admin_auth_headers, api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class StatisticsE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup()
        cls.seller_id = ObjectId()
        cls.store_name = store_name(cls.seller_id)
        cls.headers = admin_auth_headers()
        day = day_params(ISOLATED_DAY)
        with api_client() as client:
            cls.orders_before = client.get("/api/admin/stats/orders", params=day, headers=cls.headers).json()
            cls.sales_before = client.get("/api/admin/stats/orders/sales", params=day, headers=cls.headers).json()
            cls.revenue_before = client.get("/api/admin/stats/revenue", params=day, headers=cls.headers).json()
            cls.summary_before = client.get("/api/admin/stats/summary", params=summary_params(), headers=cls.headers).json()
            cls.locations_before = client.get("/api/admin/stats/orders/locations", params=day, headers=cls.headers).json()
            cls.provinces_before = client.get("/api/admin/stats/businesses-by-province", headers=cls.headers).json()
        seed_history(cls.seller_id, cls.store_name)

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup()

    def test_admin_stats_reject_other_sessions_and_a_half_open_range(self) -> None:
        seller_headers = seller_auth_headers(seller_id=str(ObjectId()), store_name="Ajena")
        with api_client() as client:
            missing = client.get("/api/admin/stats/summary")
            seller = client.get("/api/admin/stats/summary", headers=seller_headers)
            half = client.get(
                "/api/admin/stats/orders",
                params={"granularity": "daily", "start": ISOLATED_DAY.isoformat()},
                headers=self.headers,
            )
            future = client.get(
                "/api/admin/stats/orders",
                params={"granularity": "daily", "start": "2099-01-01", "end": "2099-01-02"},
                headers=self.headers,
            )
            invalid_visit = client.post(
                "/api/marketplace/visits",
                json=visit_payload(tracked_id(), province_id="no-existe"),
            )

        self.assertEqual(missing.status_code, 401, missing.text)
        self.assertEqual(seller.status_code, 401, seller.text)
        self.assertEqual(half.status_code, 400, half.text)
        self.assertEqual(future.status_code, 400, future.text)
        self.assertEqual(invalid_visit.status_code, 400, invalid_visit.text)

    def test_a_visit_is_counted_once_in_traffic_location_and_hour(self) -> None:
        day = today()
        params = day_params(day)
        place_params = {"start": day.isoformat(), "end": day.isoformat()}
        payload = visit_payload(tracked_id())
        with api_client() as client:
            before = client.get("/api/admin/stats/traffic", params=params, headers=self.headers).json()
            places_before = client.get("/api/admin/stats/traffic/locations", params=place_params, headers=self.headers).json()
            patterns_before = client.get("/api/admin/stats/traffic/patterns", params=place_params, headers=self.headers).json()
            recorded = client.post("/api/marketplace/visits", json=payload)
            duplicate = client.post("/api/marketplace/visits", json=payload)
            traffic = client.get("/api/admin/stats/traffic", params=params, headers=self.headers).json()
            places = client.get("/api/admin/stats/traffic/locations", params=place_params, headers=self.headers).json()
            patterns = client.get("/api/admin/stats/traffic/patterns", params=place_params, headers=self.headers).json()

        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertEqual(recorded.json(), {"recorded": True, "duplicate": False})
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json(), {"recorded": False, "duplicate": True})
        self.assertEqual(traffic["total_visits"], before["total_visits"] + 1)
        self.assertEqual(sum(point["count"] for point in traffic["points"]), traffic["total_visits"])
        self.assertEqual(
            count_for(places["municipalities"], province_id=PROVINCE_ID, municipality_id=SELLER_MUNICIPALITY_ID),
            count_for(places_before["municipalities"], province_id=PROVINCE_ID, municipality_id=SELLER_MUNICIPALITY_ID) + 1,
        )
        playa = next(item for item in places["municipalities"] if item["municipality_id"] == SELLER_MUNICIPALITY_ID)
        self.assertEqual(playa["province_name"], "La Habana")
        self.assertEqual(playa["municipality_name"], "Playa")
        self.assertEqual(patterns["total_visits"], patterns_before["total_visits"] + 1)
        self.assertEqual(sum(point["count"] for point in patterns["by_hour"]), patterns["total_visits"])

    def test_device_presence_stays_on_the_live_map_and_a_past_day_keeps_the_session(self) -> None:
        day = today()
        signed_in_id = tracked_id()
        params = day_params(day)
        with api_client() as client:
            before = client.get("/api/admin/stats/devices", params=params, headers=self.headers).json()
            signed_in = client.post("/api/marketplace/devices/presence", json=seller_presence(signed_in_id))
            logged_out = client.post("/api/marketplace/devices/presence", json=logged_out_presence(signed_in_id))
            anonymous = client.post("/api/marketplace/devices/presence", json=anonymous_presence(tracked_id()))
            web = client.post("/api/marketplace/devices/presence", json=web_buyer_presence(tracked_id()))
            live = client.get("/api/admin/stats/devices", params=params, headers=self.headers).json()

        self.assertEqual(signed_in.status_code, 200, signed_in.text)
        self.assertEqual(logged_out.status_code, 200, logged_out.text)
        self.assertEqual(anonymous.status_code, 200, anonymous.text)
        self.assertEqual(web.status_code, 200, web.text)
        self.assertTrue(live["live"])
        self.assertGreaterEqual(live["registered"], before["registered"] + 3)
        self.assertGreaterEqual(live["active_now"], before["active_now"] + 3)
        self.assertEqual(live["signed_in_now"], before["signed_in_now"])
        today_point = next(point for point in live["points"] if point["key"] == day.isoformat())
        before_point = next((point for point in before["points"] if point["key"] == day.isoformat()), None)
        before_close = 0 if before_point is None else before_point["close"]
        self.assertGreaterEqual(today_point["close"], before_close + 3)
        live_pins = [marker for marker in live["markers"] if same_point(marker, LIVE_LAT, LIVE_LNG)]
        self.assertEqual(len(live_pins), 1)
        pin = live_pins[0]
        self.assertTrue(pin["active"])
        self.assertFalse(pin["signed_in"])
        self.assertIsNone(pin["session_kind"])
        self.assertEqual(pin["platform"], "android")
        web_pins = [marker for marker in live["markers"] if same_point(marker, WEB_LAT, WEB_LNG)]
        self.assertEqual(len(web_pins), 1)
        self.assertEqual(web_pins[0]["platform"], "web")
        self.assertEqual(web_pins[0]["session_kind"], "buyer")
        self.assertFalse(web_pins[0]["signed_in"])

        saved_day = device_day(signed_in_id, day.isoformat())
        self.assertIsNotNone(saved_day)
        self.assertTrue(saved_day["signed_in"])
        self.assertEqual(saved_day["session_kind"], "seller")

        seed_past_device_day(tracked_id())
        with api_client() as client:
            past = client.get("/api/admin/stats/devices", params=day_params(ISOLATED_DAY), headers=self.headers).json()

        self.assertFalse(past["live"])
        self.assertEqual(past["map_day"], ISOLATED_DAY.isoformat())
        past_pin = next(marker for marker in past["markers"] if same_point(marker, PAST_LAT, PAST_LNG))
        self.assertFalse(past_pin["active"])
        self.assertTrue(past_pin["signed_in"])
        self.assertEqual(past_pin["session_kind"], "gestor")

    def test_isolated_day_feeds_orders_sales_revenue_and_province(self) -> None:
        day = day_params(ISOLATED_DAY)
        with api_client() as client:
            orders = client.get("/api/admin/stats/orders", params=day, headers=self.headers).json()
            weekly_orders = client.get("/api/admin/stats/orders", params=day_params(ISOLATED_DAY, "weekly"), headers=self.headers).json()
            sales = client.get("/api/admin/stats/orders/sales", params=day, headers=self.headers).json()
            top = client.get("/api/admin/stats/orders/top-businesses", params=day, headers=self.headers).json()
            locations = client.get("/api/admin/stats/orders/locations", params=day, headers=self.headers).json()
            revenue = client.get("/api/admin/stats/revenue", params=day, headers=self.headers).json()
            summary = client.get("/api/admin/stats/summary", params=summary_params(), headers=self.headers).json()
            provinces = client.get("/api/admin/stats/businesses-by-province", headers=self.headers).json()

        self.assertEqual(orders["total_orders"], self.orders_before["total_orders"] + 2)
        self.assertEqual(weekly_orders["total_orders"], orders["total_orders"])
        point = next(item for item in orders["points"] if item["key"] == ISOLATED_DAY.isoformat())
        self.assertEqual(point["count"], self.orders_before["total_orders"] + 2)
        self.assertEqual(point["open"], 0)
        self.assertEqual(point["close"], point["count"])
        self.assertEqual(sales["orders_counted"], self.sales_before["orders_counted"] + 1)
        self.assertEqual(sales["total_cup"], self.sales_before["total_cup"] + CUP_COLLECTED)
        business = next(item for item in top["businesses"] if item["seller_id"] == str(self.seller_id))
        self.assertEqual(business["store_name"], self.store_name)
        self.assertEqual(business["count"], 2)
        self.assertEqual(business["province_name"], "La Habana")
        self.assertEqual(business["municipality_name"], "Playa")
        self.assertEqual(
            count_for(locations["provinces"], province_id=PROVINCE_ID),
            count_for(self.locations_before["provinces"], province_id=PROVINCE_ID) + 2,
        )
        self.assertEqual(
            count_for(locations["municipalities"], province_id=PROVINCE_ID, municipality_id=SELLER_MUNICIPALITY_ID),
            count_for(
                self.locations_before["municipalities"],
                province_id=PROVINCE_ID,
                municipality_id=SELLER_MUNICIPALITY_ID,
            )
            + 2,
        )
        self.assertEqual(revenue["total_cup"], self.revenue_before["total_cup"] + int(PAYMENT_CUP))
        self.assertEqual(revenue["payments_count"], self.revenue_before["payments_count"] + 1)
        self.assertEqual(summary["payments_total_cup"], self.summary_before["payments_total_cup"] + int(PAYMENT_CUP))
        self.assertEqual(summary["payments_count"], self.summary_before["payments_count"] + 1)
        self.assertEqual(
            count_for(provinces["provinces"], province_id=PROVINCE_ID),
            count_for(self.provinces_before["provinces"], province_id=PROVINCE_ID) + 1,
        )

    def test_isolated_day_ranks_sold_units_and_popularity_points(self) -> None:
        day = day_params(ISOLATED_DAY)
        with api_client() as client:
            sold = client.get("/api/admin/stats/products/sold", params=day, headers=self.headers)
            popular = client.get("/api/admin/stats/products/popular", params=day, headers=self.headers)

        self.assertEqual(sold.status_code, 200, sold.text)
        self.assertEqual(popular.status_code, 200, popular.text)
        sold_body = sold.json()
        popular_body = popular.json()
        sold_by_name = {item["name"]: item for item in sold_body["products"]}
        popular_by_name = {item["name"]: item for item in popular_body["products"]}

        lead = sold_by_name[SOLD_LEAD_NAME]
        second = sold_by_name[SOLD_SECOND_NAME]
        self.assertEqual(lead["quantity"], 6)
        self.assertEqual(lead["amount_cup"], 400)
        self.assertEqual(lead["store_name"], self.store_name)
        self.assertEqual(second["quantity"], 1)
        self.assertEqual(second["amount_cup"], 50)
        self.assertLess(
            sold_body["products"].index(lead),
            sold_body["products"].index(second),
        )
        self.assertGreaterEqual(sold_body["total_units"], 7)

        popular_lead = popular_by_name[SOLD_LEAD_NAME]
        popular_second = popular_by_name[SOLD_SECOND_NAME]
        self.assertEqual(popular_lead["points"], 1)
        self.assertEqual(popular_lead["views"], 1)
        self.assertEqual(popular_lead["jaba"], 0)
        self.assertEqual(popular_lead["purchases"], 0)
        self.assertEqual(popular_second["points"], 3)
        self.assertEqual(popular_second["views"], 1)
        self.assertEqual(popular_second["jaba"], 1)
        self.assertEqual(popular_second["purchases"], 0)
        self.assertEqual(popular_second["store_name"], self.store_name)
        self.assertLess(
            popular_body["products"].index(popular_second),
            popular_body["products"].index(popular_lead),
        )
        self.assertGreaterEqual(popular_body["total_points"], 4)
