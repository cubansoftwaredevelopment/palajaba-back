"""Fechas y guardado de las secciones del mensajero."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.account_sync.compare import as_iso, newest, section_clock, section_verdict, verdicts_for
from app.database import get_mensajeria_batches_collection, get_mensajeros_collection
from app.mensajeros.utils import VEHICLE_TYPES
from app.utils.datetime import to_utc_naive, utc_now

SECTIONS = ("perfil", "vehiculos", "rutas")


def _now() -> datetime:
    return to_utc_naive(utc_now())


async def _doc(mensajero_id: str) -> dict[str, Any]:
    doc = await get_mensajeros_collection().find_one({"_id": ObjectId(mensajero_id)})
    if not doc or doc.get("is_active", True) is False:
        raise HTTPException(status_code=401, detail="La cuenta del mensajero no está activa.")
    return doc


async def server_dates(mensajero_id: str) -> dict[str, datetime | None]:
    doc = await _doc(mensajero_id)
    batch = await get_mensajeria_batches_collection().find_one(
        {"mensajero_id": doc["_id"]},
        {"updated_at": 1},
        sort=[("updated_at", -1)],
    )
    route_at = batch.get("updated_at") if batch and isinstance(batch.get("updated_at"), datetime) else None
    perfil = section_clock(doc, "perfil") or (doc.get("created_at") if isinstance(doc.get("created_at"), datetime) else None)
    vehicles = section_clock(doc, "vehiculos") or (doc.get("updated_at") if isinstance(doc.get("updated_at"), datetime) else None)
    return {
        "perfil": to_utc_naive(perfil) if isinstance(perfil, datetime) else None,
        "vehiculos": to_utc_naive(vehicles) if isinstance(vehicles, datetime) else None,
        "rutas": newest(section_clock(doc, "rutas"), route_at),
    }


async def compare_mensajero(mensajero_id: str, phone_dates: dict[str, Any]) -> dict[str, bool | None]:
    return verdicts_for(await server_dates(mensajero_id), phone_dates)


async def apply_mensajero_section(mensajero_id: str, section: str, updated_at: Any, data: Any) -> dict[str, Any]:
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Esa sección no existe.")
    dates = await server_dates(mensajero_id)
    if section_verdict(updated_at, dates[section]) is not True:
        raise HTTPException(status_code=409, detail="El servidor tiene una copia más reciente de esta sección.")
    doc = await _doc(mensajero_id)
    now = _now()
    fields: dict[str, Any] = {"updated_at": now, f"section_updated_at.{section}": now}
    saved: Any = {"kept": True}
    if section == "vehiculos" and isinstance(data, list):
        current = {item.get("id"): item for item in doc.get("vehicles") or [] if item.get("id")}
        vehicles = []
        for item in data:
            if not isinstance(item, dict):
                continue
            vehicle_type = str(item.get("vehicle_type") or "")
            if vehicle_type not in VEHICLE_TYPES:
                continue
            vehicle_id = str(item.get("id") or ObjectId())
            owned = current.get(vehicle_id) or {}
            vehicles.append({
                "id": vehicle_id,
                "vehicle_type": vehicle_type,
                "plate": str(item.get("plate") or owned.get("plate") or "")[:16],
                "photo_url": owned.get("photo_url"),
                "photo_urls": owned.get("photo_urls") or [],
            })
        fields["vehicles"] = vehicles
        saved = vehicles
    await get_mensajeros_collection().update_one({"_id": doc["_id"]}, {"$set": fields})
    return {"updated_at": as_iso(now), "data": saved}
