"""Visitas y presencia de dispositivos."""

from datetime import datetime

from bson import ObjectId

from test_e2e.statistics.fixtures.constants import (
    ID_PREFIX,
    ISOLATED_DAY,
    LIVE_LAT,
    LIVE_LNG,
    PAST_LAT,
    PAST_LNG,
    WEB_LAT,
    WEB_LNG,
)
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


def tracked_id() -> str:
    return f"{ID_PREFIX}{ObjectId()}"


def visit_payload(session_id: str, *, province_id: str = PROVINCE_ID, municipality_id: str = SELLER_MUNICIPALITY_ID) -> dict:
    return {
        "session_id": session_id,
        "page": "marketplace",
        "province_id": province_id,
        "municipality_id": municipality_id,
    }


def presence_payload(
    device_id: str,
    *,
    platform: str,
    lat: float | None = None,
    lng: float | None = None,
    session_kind: str | None = None,
) -> dict:
    payload: dict = {"device_id": device_id, "platform": platform}
    if lat is not None and lng is not None:
        payload["lat"] = lat
        payload["lng"] = lng
    if session_kind is not None:
        payload["session_kind"] = session_kind
    return payload


def seller_presence(device_id: str) -> dict:
    return presence_payload(device_id, platform="android", lat=LIVE_LAT, lng=LIVE_LNG, session_kind="seller")


def logged_out_presence(device_id: str) -> dict:
    return presence_payload(device_id, platform="android", lat=LIVE_LAT, lng=LIVE_LNG)


def anonymous_presence(device_id: str) -> dict:
    return presence_payload(device_id, platform="ios")


def web_buyer_presence(device_id: str) -> dict:
    return presence_payload(
        device_id,
        platform="web",
        lat=WEB_LAT,
        lng=WEB_LNG,
        session_kind="buyer",
    )


def past_device_day(device_id: str) -> dict:
    moment = datetime(ISOLATED_DAY.year, ISOLATED_DAY.month, ISOLATED_DAY.day, 16, 0)
    return {
        "device_id": device_id,
        "day": ISOLATED_DAY.isoformat(),
        "platform": "android",
        "lat": PAST_LAT,
        "lng": PAST_LNG,
        "signed_in": True,
        "session_kind": "gestor",
        "first_seen": moment,
        "last_seen": moment,
    }
