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
from test_e2e.statistics.fixtures.constants import ID_PREFIX, ISOLATED_DAY, MARKER
from test_e2e.statistics.fixtures.history import (
    completed_orders,
    payment_document,
    popularity_events,
    product_documents,
    seller_document,
)
from test_e2e.statistics.fixtures.presence import past_device_day
from test_e2e.utils.database import run_db


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
