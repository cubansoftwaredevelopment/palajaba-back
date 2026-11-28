"""Fechas y guardado de las secciones del admin."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.account_sync.compare import as_iso, newest, section_verdict, verdicts_for
from app.admin.service import SETTINGS_ID
from app.database import get_orders_collection, get_platform_settings_collection, get_registrations_collection
from app.utils.datetime import to_utc_naive, utc_now

SECTIONS = ("ajustes", "estadisticas", "aprobaciones", "cuentas")


def _now() -> datetime:
    return to_utc_naive(utc_now())


def _clock(settings: dict[str, Any] | None, admin_id: str, name: str) -> datetime | None:
    clocks = ((settings or {}).get("admin_section_clocks") or {}).get(admin_id) or {}
    value = clocks.get(name)
    return to_utc_naive(value) if isinstance(value, datetime) else None


async def _latest(collection) -> datetime | None:
    doc = await collection.find_one({}, {"updated_at": 1}, sort=[("updated_at", -1)])
    if not doc or not isinstance(doc.get("updated_at"), datetime):
        return None
    return to_utc_naive(doc["updated_at"])


async def server_dates(admin_id: str) -> dict[str, datetime | None]:
    settings = await get_platform_settings_collection().find_one(
        {"_id": SETTINGS_ID},
        {"updated_at": 1, "admin_section_clocks": 1},
    )
    settings_at = settings.get("updated_at") if settings and isinstance(settings.get("updated_at"), datetime) else None
    registrations = await _latest(get_registrations_collection())
    orders = await _latest(get_orders_collection())
    return {
        "ajustes": settings_at or _clock(settings, admin_id, "ajustes"),
        "estadisticas": newest(_clock(settings, admin_id, "estadisticas"), orders),
        "aprobaciones": newest(_clock(settings, admin_id, "aprobaciones"), registrations),
        "cuentas": newest(_clock(settings, admin_id, "cuentas"), registrations),
    }


async def compare_admin(admin_id: str, phone_dates: dict[str, Any]) -> dict[str, bool | None]:
    return verdicts_for(await server_dates(admin_id), phone_dates)


async def apply_admin_section(admin_id: str, section: str, updated_at: Any, data: Any) -> dict[str, Any]:
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Esa sección no existe.")
    dates = await server_dates(admin_id)
    if section_verdict(updated_at, dates[section]) is not True:
        raise HTTPException(status_code=409, detail="El servidor tiene una copia más reciente de esta sección.")
    now = _now()
    saved: Any = {"kept": True}
    if section == "ajustes" and isinstance(data, dict) and data.get("renewal_contact_phone") is not None:
        phone = str(data.get("renewal_contact_phone") or "").strip()
        await get_platform_settings_collection().update_one(
            {"_id": SETTINGS_ID},
            {"$set": {"renewal_contact_phone": phone, "updated_at": now}},
            upsert=True,
        )
        saved = {"renewal_contact_phone": phone}
    await get_platform_settings_collection().update_one(
        {"_id": SETTINGS_ID},
        {"$set": {f"admin_section_clocks.{admin_id}.{section}": now}},
        upsert=True,
    )
    return {"updated_at": as_iso(now), "data": saved}
