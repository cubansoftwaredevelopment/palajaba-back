"""Presencia de la app y del navegador: dispositivos, uso por día y mapa."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pymongo import ASCENDING

from app.database import get_app_device_days_collection, get_app_devices_collection
from app.statistics_admin.schemas.devices import AdminDeviceStats, DeviceMapMarker, DevicePresenceRequest
from app.statistics_admin.schemas.traffic import TrafficDataPoint
from app.statistics_admin.utils import build_level_candles, parse_inclusive_dates, ranges_between
from app.utils.datetime import to_utc_naive, utc_now

DeviceGranularity = Literal["daily", "weekly", "monthly"]
ACTIVE_WINDOW = timedelta(seconds=90)
TRACKED_PLATFORMS = ("android", "ios", "web")
ACCOUNT_KINDS = {"seller", "gestor"}
MAP_MARKER_LIMIT = 500


async def ensure_app_device_indexes() -> None:
    devices = get_app_devices_collection()
    days = get_app_device_days_collection()
    await devices.create_index([("device_id", ASCENDING)], unique=True)
    await devices.create_index([("last_seen", ASCENDING)])
    await days.create_index([("device_id", ASCENDING), ("day", ASCENDING)], unique=True)
    await days.create_index([("day", ASCENDING)])


def _day_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _today() -> date:
    now = to_utc_naive(utc_now())
    return date(now.year, now.month, now.day)


def default_device_window(
    granularity: DeviceGranularity,
    year: int | None = None,
    month: int | None = None,
) -> tuple[datetime, datetime]:
    today = _today()
    if granularity == "daily":
        return parse_inclusive_dates(today, today)
    if granularity == "weekly":
        return parse_inclusive_dates(today - timedelta(days=6), today)
    start = date(today.year, today.month, 1)
    if year is not None and month is not None:
        start = date(year, month, 1)
        if (year, month) != (today.year, today.month):
            last_day = calendar.monthrange(year, month)[1]
            return parse_inclusive_dates(start, date(year, month, last_day))
    return parse_inclusive_dates(start, today)


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
    account_session = payload.session_kind in ACCOUNT_KINDS
    if account_session:
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
    if not account_session:
        insert_fields["signed_in"] = False
        if payload.session_kind == "buyer":
            insert_fields["session_kind"] = "buyer"
    await get_app_device_days_collection().update_one(
        {"device_id": payload.device_id, "day": day},
        {"$set": day_set, "$setOnInsert": insert_fields},
        upsert=True,
    )


def _doc_seen_at(doc: dict[str, Any]) -> datetime:
    value = doc.get("last_seen") or doc.get("first_seen")
    if isinstance(value, datetime):
        return to_utc_naive(value)
    return datetime.min


def _marker_from_doc(doc: dict[str, Any], *, active: bool) -> DeviceMapMarker | None:
    lat = doc.get("lat")
    lng = doc.get("lng")
    if lat is None or lng is None:
        return None
    kind = doc.get("session_kind")
    if kind not in {"seller", "gestor", "buyer"}:
        kind = None
    platform = doc.get("platform")
    if platform not in TRACKED_PLATFORMS:
        platform = None
    signed_in = bool(doc.get("signed_in") or kind in ACCOUNT_KINDS)
    return DeviceMapMarker(
        lat=float(lat),
        lng=float(lng),
        platform=platform,
        signed_in=signed_in,
        session_kind=kind,
        active=active,
    )


async def earliest_device_day() -> date | None:
    earliest_day = await get_app_device_days_collection().find_one(
        {"day": {"$regex": r"^\d{4}-\d{2}-\d{2}$"}},
        sort=[("day", 1)],
        projection={"day": 1},
    )
    if earliest_day:
        try:
            parsed = datetime.strptime(str(earliest_day.get("day") or ""), "%Y-%m-%d")
        except ValueError:
            parsed = None
        if parsed is not None:
            return date(parsed.year, parsed.month, parsed.day)

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

    tracked = {"platform": {"$in": list(TRACKED_PLATFORMS)}}
    registered = await devices.count_documents(tracked)
    active_now = await devices.count_documents({**tracked, "last_seen": {"$gte": active_since}})
    signed_in_now = await devices.count_documents(
        {
            **tracked,
            "last_seen": {"$gte": active_since},
            "session_kind": {"$in": list(ACCOUNT_KINDS)},
        }
    )

    ranges = ranges_between(start, end, granularity)
    start_day = _day_key(start)
    end_day = _day_key(end)
    map_day = _day_key(end - timedelta(seconds=1)) if end > start else start_day
    day_docs = await days.find(
        {"day": {"$gte": start_day, "$lt": end_day}},
        projection={
            "device_id": 1,
            "day": 1,
            "lat": 1,
            "lng": 1,
            "platform": 1,
            "session_kind": 1,
            "signed_in": 1,
            "first_seen": 1,
            "last_seen": 1,
        },
    ).to_list(length=None)

    values: dict[str, float] = {key: 0.0 for key, _, _, _ in ranges}
    seen: dict[str, set[str]] = {key: set() for key, _, _, _ in ranges}
    latest_by_device: dict[str, dict[str, Any]] = {}
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
        previous = latest_by_device.get(device_id)
        if previous is None or _doc_seen_at(doc) >= _doc_seen_at(previous):
            latest_by_device[device_id] = doc
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
    active_ids: set[str] = set()
    if live:
        active_docs = await devices.find(
            {
                "platform": {"$in": list(TRACKED_PLATFORMS)},
                "last_seen": {"$gte": active_since},
                "lat": {"$ne": None},
                "lng": {"$ne": None},
            }
        ).to_list(length=MAP_MARKER_LIMIT)
        for doc in active_docs:
            device_id = str(doc.get("device_id") or "")
            if not device_id:
                continue
            latest_by_device[device_id] = doc
            active_ids.add(device_id)

    ranked = sorted(
        latest_by_device.items(),
        key=lambda item: _doc_seen_at(item[1]),
        reverse=True,
    )
    markers: list[DeviceMapMarker] = []
    for device_id, doc in ranked:
        if len(markers) >= MAP_MARKER_LIMIT:
            break
        marker = _marker_from_doc(doc, active=device_id in active_ids)
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
