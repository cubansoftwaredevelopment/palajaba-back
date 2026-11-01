"""Limpieza, siembra y lecturas del recorrido de estadísticas."""

from datetime import date

from bson import ObjectId

from app.database import (
    get_app_device_days_collection,
    get_app_devices_collection,
    get_catalog_products_collection,
    get_marketplace_visits_collection,
    get_orders_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
    get_subscription_payments_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.statistics.utils.data.constants import ID_PREFIX, ISOLATED_DAY, MARKER
from test_e2e.statistics.utils.data.history import (
    completed_orders,
    payment_document,
    popularity_events,
    product_documents,
    seller_document,
)
from test_e2e.statistics.utils.data.presence import past_device_day
from test_e2e.utils.database import run_db

from test_e2e.statistics.utils.data.constants import (
    CUP_COLLECTED,
    DELIVERY_ADDRESS,
    DELIVERY_LAT,
    DELIVERY_LNG,
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
from test_e2e.statistics.utils.data.history import store_name
from test_e2e.statistics.utils.data.presence import (
    anonymous_presence,
    logged_out_presence,
    seller_presence,
    tracked_id,
    visit_payload,
    web_buyer_presence,
)


def today() -> date:
    now = to_utc_naive(utc_now())
    return date(now.year, now.month, now.day)


def day_params(day: date, granularity: str = "daily") -> dict[str, str]:
    iso = day.isoformat()
    return {"granularity": granularity, "start": iso, "end": iso}


def same_point(marker: dict, lat: float, lng: float) -> bool:
    return abs(float(marker["lat"]) - lat) < 0.0001 and abs(float(marker["lng"]) - lng) < 0.0001


def count_for(items: list[dict], *, province_id: str, municipality_id: str | None = None) -> int:
    for item in items:
        if item.get("province_id") != province_id:
            continue
        if municipality_id is not None and item.get("municipality_id") != municipality_id:
            continue
        return int(item["count"])
    return 0


def cleanup() -> None:
    async def work() -> None:
        await get_registrations_collection().delete_many({"statistics_e2e_marker": MARKER})
        await get_orders_collection().delete_many({"statistics_e2e_marker": MARKER})
        await get_subscription_payments_collection().delete_many({"statistics_e2e_marker": MARKER})
        await get_catalog_products_collection().delete_many({"statistics_e2e_marker": MARKER})
        await get_product_popularity_events_collection().delete_many({"statistics_e2e_marker": MARKER})
        tracked = {"$regex": rf"^{ID_PREFIX}"}
        await get_marketplace_visits_collection().delete_many({"session_id": tracked})
        await get_app_devices_collection().delete_many({"device_id": tracked})
        await get_app_device_days_collection().delete_many({"device_id": tracked})

    run_db(work)


def seed_history(seller_id: ObjectId, name: str) -> None:
    async def work() -> None:
        lead_id = ObjectId()
        second_id = ObjectId()
        await get_registrations_collection().insert_one(seller_document(seller_id, name))
        await get_catalog_products_collection().insert_many(product_documents(seller_id, lead_id, second_id))
        await get_orders_collection().insert_many(completed_orders(seller_id, name, lead_id, second_id))
        await get_product_popularity_events_collection().insert_many(
            popularity_events(seller_id, lead_id, second_id)
        )
        await get_subscription_payments_collection().insert_one(payment_document())

    run_db(work)


def seed_past_device_day(device_id: str) -> None:
    async def work() -> None:
        await get_app_device_days_collection().insert_one(past_device_day(device_id))

    run_db(work)


def device_day(device_id: str, day: str) -> dict | None:
    async def work() -> dict | None:
        return await get_app_device_days_collection().find_one({"device_id": device_id, "day": day})

    return run_db(work)


def summary_params() -> dict[str, int]:
    return {"year": ISOLATED_DAY.year, "month": ISOLATED_DAY.month}


def setup_statistics_e2e() -> dict:
    """Limpia, recoge métricas de referencia y siembra el día aislado."""
    from test_e2e.utils.api import admin_auth_headers, api_client

    cleanup()
    seller_id = ObjectId()
    name = store_name(seller_id)
    headers = admin_auth_headers()
    day = day_params(ISOLATED_DAY)
    with api_client() as client:
        baseline = {
            "orders_before": client.get("/api/admin/stats/orders", params=day, headers=headers).json(),
            "sales_before": client.get("/api/admin/stats/orders/sales", params=day, headers=headers).json(),
            "revenue_before": client.get("/api/admin/stats/revenue", params=day, headers=headers).json(),
            "summary_before": client.get("/api/admin/stats/summary", params=summary_params(), headers=headers).json(),
            "locations_before": client.get("/api/admin/stats/orders/locations", params=day, headers=headers).json(),
            "delivery_before": client.get("/api/admin/stats/orders/delivery-map", params=day, headers=headers).json(),
            "provinces_before": client.get("/api/admin/stats/businesses-by-province", headers=headers).json(),
        }
    seed_history(seller_id, name)
    return {
        "seller_id": seller_id,
        "store_name": name,
        "headers": headers,
        **baseline,
    }
