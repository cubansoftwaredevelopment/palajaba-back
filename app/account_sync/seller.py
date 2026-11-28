"""Fechas y guardado de las secciones de la tienda."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.account_sync.compare import as_iso, newest, section_clock, section_verdict, verdicts_for
from app.database import (
    get_catalog_products_collection,
    get_notifications_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now

SECTIONS = ("perfil", "catalogo", "pedidos", "clientes", "avisos", "estadisticas")


def _now() -> datetime:
    return to_utc_naive(utc_now())


async def _seller(seller_id: str) -> dict[str, Any]:
    doc = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    if not doc or doc.get("deleted_at"):
        raise HTTPException(status_code=401, detail="Cuenta de tienda no encontrada.")
    return doc


def _fallback(doc: dict[str, Any], name: str) -> datetime | None:
    clock = section_clock(doc, name)
    if clock is not None:
        return clock
    if name == "perfil":
        created = doc.get("created_at")
        if isinstance(created, datetime):
            return to_utc_naive(created)
    return None


async def _latest(collection, query: dict[str, Any]) -> datetime | None:
    doc = await collection.find_one(query, {"updated_at": 1}, sort=[("updated_at", -1)])
    if not doc or not isinstance(doc.get("updated_at"), datetime):
        return None
    return to_utc_naive(doc["updated_at"])


async def server_dates(seller_id: str) -> dict[str, datetime | None]:
    doc = await _seller(seller_id)
    seller_match = {"seller_id": {"$in": [seller_id, ObjectId(seller_id)]}}
    orders = await _latest(get_orders_collection(), seller_match)
    products = await _latest(get_catalog_products_collection(), {**seller_match, "deleted_at": {"$exists": False}})
    notices = await _latest(get_notifications_collection(), seller_match)
    return {
        "perfil": _fallback(doc, "perfil"),
        "catalogo": newest(section_clock(doc, "catalogo"), products),
        "pedidos": newest(section_clock(doc, "pedidos"), orders),
        "clientes": newest(section_clock(doc, "clientes"), orders),
        "avisos": newest(section_clock(doc, "avisos"), notices),
        "estadisticas": newest(section_clock(doc, "estadisticas"), orders),
    }


async def compare_seller(seller_id: str, phone_dates: dict[str, Any]) -> dict[str, bool | None]:
    return verdicts_for(await server_dates(seller_id), phone_dates)


async def apply_seller_section(seller_id: str, section: str, updated_at: Any, data: Any) -> dict[str, Any]:
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Esa sección no existe.")
    dates = await server_dates(seller_id)
    if section_verdict(updated_at, dates[section]) is not True:
        raise HTTPException(status_code=409, detail="El servidor tiene una copia más reciente de esta sección.")
    now = _now()
    oid = ObjectId(seller_id)
    fields: dict[str, Any] = {"updated_at": now, f"section_updated_at.{section}": now}
    saved: Any = {"kept": True}
    if section == "perfil" and isinstance(data, dict):
        for key in (
            "biography",
            "social_instagram",
            "social_facebook",
            "social_links",
            "offers_delivery",
            "gestores_enabled",
            "business_area",
            "delivery_areas",
            "category_ids",
            "catalog_theme",
            "catalog_palette",
            "store_pages",
            "gestor_catalog_access",
        ):
            if key in data:
                fields[key] = data[key]
        saved = {key: fields[key] for key in fields if key not in ("updated_at",) and not key.startswith("section_")}
    elif section == "catalogo" and isinstance(data, list):
        products = get_catalog_products_collection()
        changed = 0
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            try:
                product_id = ObjectId(str(item["id"]))
            except Exception:
                continue
            patch: dict[str, Any] = {"updated_at": now}
            if isinstance(item.get("name"), str) and item["name"].strip():
                patch["name"] = item["name"].strip()
            if item.get("base_price") is not None:
                patch["base_price"] = float(item["base_price"])
            result = await products.update_one(
                {"_id": product_id, "seller_id": {"$in": [seller_id, oid]}, "deleted_at": {"$exists": False}},
                {"$set": patch},
            )
            changed += result.modified_count
        saved = {"updated": changed}
    await get_registrations_collection().update_one({"_id": oid}, {"$set": fields})
    return {"updated_at": as_iso(now), "data": saved}
