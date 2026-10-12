"""Presencia de la app nativa: dispositivos, uso por día y mapa."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from pymongo import ASCENDING

from app.database import get_app_device_days_collection, get_app_devices_collection
from app.statistics_admin.schemas.devices import AdminDeviceStats, DeviceMapMarker, DevicePresenceRequest
from app.statistics_admin.schemas.traffic import TrafficDataPoint
from app.statistics_admin.utils import build_level_candles, ranges_between
from app.utils.datetime import to_utc_naive, utc_now

DeviceGranularity = Literal["daily", "weekly", "monthly"]
ACTIVE_WINDOW = timedelta(seconds=90)


async def ensure_app_device_indexes() -> None:
    devices = get_app_devices_collection()
    days = get_app_device_days_collection()
    await devices.create_index([("device_id", ASCENDING)], unique=True)
    await devices.create_index([("last_seen", ASCENDING)])
    await days.create_index([("device_id", ASCENDING), ("day", ASCENDING)], unique=True)
    await days.create_index([("day", ASCENDING)])


def _day_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


async def record_device_presence(payload: DevicePresenceRequest) -> None:
    now = to_utc_naive(utc_now())
    day = _day_key(now)
    has_location = payload.lat is not None and payload.lng is not None

    device_set: dict[str, Any] = {
        "platform": payload.platform,
        "last_seen": now,
        "session_kind": payload.session_kind,
    }
    day_set: dict[str, Any] = {
        "platform": payload.platform,
        "last_seen": now,
    }
    if has_location:
        device_set["lat"] = payload.lat
        device_set["lng"] = payload.lng
        day_set["lat"] = payload.lat
        day_set["lng"] = payload.lng
    if payload.session_kind:
        day_set["session_kind"] = payload.session_kind
        day_set["signed_in"] = True

    await get_app_devices_collection().update_one(
        {"device_id": payload.device_id},
        {
            "$set": device_set,
            "$setOnInsert": {"device_id": payload.device_id, "first_seen": now},
        },
        upsert=True,
    )
    insert_fields: dict[str, Any] = {
        "device_id": payload.device_id,
        "day": day,
        "first_seen": now,
    }
    if not payload.session_kind:
        insert_fields["signed_in"] = False
    await get_app_device_days_collection().update_one(
        {"device_id": payload.device_id, "day": day},
        {"$set": day_set, "$setOnInsert": insert_fields},
        upsert=True,
    )


def _marker_from_doc(doc: dict[str, Any], *, active: bool) -> DeviceMapMarker | None:
    lat = doc.get("lat")
    lng = doc.get("lng")
    if lat is None or lng is None:
        return None
    kind = doc.get("session_kind")
    signed_in = bool(doc.get("signed_in") or kind)
    return DeviceMapMarker(
        lat=float(lat),
        lng=float(lng),
        signed_in=signed_in,
        session_kind=kind if kind in {"seller", "gestor"} else None,
        active=active,
    )


async def earliest_device_day() -> date | None:
    earliest = await get_app_devices_collection().find_one(
        {"first_seen": {"$type": "date"}},
        sort=[("first_seen", 1)],
        projection={"first_seen": 1},
    )
    if not earliest or not isinstance(earliest.get("first_seen"), datetime):
        return None
    seen = to_utc_naive(earliest["first_seen"])
    return date(seen.year, seen.month, seen.day)


async def get_device_stats(
    *,
    granularity: DeviceGranularity,
    start: datetime,
    end: datetime,
) -> AdminDeviceStats:
    now = to_utc_naive(utc_now())
    active_since = now - ACTIVE_WINDOW
    devices = get_app_devices_collection()
    days = get_app_device_days_collection()

    registered = await devices.count_documents({"platform": {"$in": ["android", "ios"]}})
    active_now = await devices.count_documents(
        {"platform": {"$in": ["android", "ios"]}, "last_seen": {"$gte": active_since}}
    )
    signed_in_now = await devices.count_documents(
        {
            "platform": {"$in": ["android", "ios"]},
            "last_seen": {"$gte": active_since},
            "session_kind": {"$in": ["seller", "gestor"]},
        }
    )

    ranges = ranges_between(start, end, granularity)
    day_docs = await days.find(
        {"day": {"$gte": _day_key(start), "$lt": _day_key(end)}},
        projection={"device_id": 1, "day": 1},
    ).to_list(length=None)

    values: dict[str, float] = {key: 0.0 for key, _, _, _ in ranges}
    seen: dict[str, set[str]] = {key: set() for key, _, _, _ in ranges}
    for doc in day_docs:
        day = str(doc.get("day") or "")
        device_id = str(doc.get("device_id") or "")
        if not day or not device_id:
            continue
        try:
            moment = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            continue
        for key, _, bucket_start, bucket_end in ranges:
            if bucket_start <= moment < bucket_end:
                seen[key].add(device_id)
                break
    for key, ids in seen.items():
        values[key] = float(len(ids))

    points = [
        TrafficDataPoint(
            key=str(item["key"]),
            label=str(item["label"]),
            count=int(round(float(item["bucket"]))),
            time=int(item["time"]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
        )
        for item in build_level_candles(values, ranges)
    ]

    live = start <= now < end
    markers: list[DeviceMapMarker] = []
    map_day: str | None = None
    if live:
        active_docs = await devices.find(
            {
                "platform": {"$in": ["android", "ios"]},
                "last_seen": {"$gte": active_since},
                "lat": {"$ne": None},
                "lng": {"$ne": None},
            }
        ).to_list(length=500)
        for doc in active_docs:
            marker = _marker_from_doc(doc, active=True)
            if marker:
                markers.append(marker)
    else:
        last_moment = end - timedelta(seconds=1)
        map_day = _day_key(last_moment)
        past_docs = await days.find(
            {"day": map_day, "lat": {"$ne": None}, "lng": {"$ne": None}}
        ).to_list(length=500)
        for doc in past_docs:
            marker = _marker_from_doc(doc, active=False)
            if marker:
                markers.append(marker)

    return AdminDeviceStats(
        registered=registered,
        active_now=active_now,
        signed_in_now=signed_in_now,
        live=live,
        map_day=map_day,
        points=points,
        markers=markers,
    )
