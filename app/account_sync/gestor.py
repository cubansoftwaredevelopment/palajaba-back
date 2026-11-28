"""Fechas y guardado de las secciones del gestor."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.account_sync.compare import as_iso, newest, section_clock, section_verdict, verdicts_for
from app.database import get_catalog_products_collection, get_gestores_collection
from app.gestores.service import document_to_gestor_public
from app.utils.datetime import to_utc_naive, utc_now

SECTIONS = ("perfil", "productos", "permitidos")


def _now() -> datetime:
    return to_utc_naive(utc_now())


async def _gestor(gestor_id: str, seller_id: str) -> dict[str, Any]:
    doc = await get_gestores_collection().find_one({"_id": ObjectId(gestor_id), "seller_id": ObjectId(seller_id)})
    if not doc:
        doc = await get_gestores_collection().find_one({"_id": ObjectId(gestor_id), "seller_id": seller_id})
    if not doc:
        raise HTTPException(status_code=401, detail="La cuenta de gestor ya no existe.")
    return doc


async def server_dates(gestor_id: str, seller_id: str) -> dict[str, datetime | None]:
    doc = await _gestor(gestor_id, seller_id)
    product = await get_catalog_products_collection().find_one(
        {"seller_id": {"$in": [seller_id, ObjectId(seller_id)]}, "deleted_at": {"$exists": False}},
        {"updated_at": 1},
        sort=[("updated_at", -1)],
    )
    catalog_at = product.get("updated_at") if product and isinstance(product.get("updated_at"), datetime) else None
    perfil = section_clock(doc, "perfil") or (doc.get("created_at") if isinstance(doc.get("created_at"), datetime) else None)
    productos = section_clock(doc, "productos") or (doc.get("updated_at") if isinstance(doc.get("updated_at"), datetime) else None)
    return {
        "perfil": to_utc_naive(perfil) if isinstance(perfil, datetime) else None,
        "productos": to_utc_naive(productos) if isinstance(productos, datetime) else None,
        "permitidos": newest(section_clock(doc, "permitidos"), catalog_at),
    }


async def compare_gestor(gestor_id: str, seller_id: str, phone_dates: dict[str, Any]) -> dict[str, bool | None]:
    return verdicts_for(await server_dates(gestor_id, seller_id), phone_dates)


async def apply_gestor_section(gestor_id: str, seller_id: str, section: str, updated_at: Any, data: Any) -> dict[str, Any]:
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Esa sección no existe.")
    dates = await server_dates(gestor_id, seller_id)
    if section_verdict(updated_at, dates[section]) is not True:
        raise HTTPException(status_code=409, detail="El servidor tiene una copia más reciente de esta sección.")
    doc = await _gestor(gestor_id, seller_id)
    now = _now()
    fields: dict[str, Any] = {"updated_at": now, f"section_updated_at.{section}": now}
    saved: Any = {"kept": True}
    if section == "productos" and isinstance(data, list):
        selected = []
        for item in data:
            if not isinstance(item, dict) or not item.get("product_id"):
                continue
            selected.append({
                "product_id": str(item["product_id"]),
                "margin_amount": float(item.get("margin_amount") or 0),
            })
        fields["selected_products"] = selected
        saved = selected
    await get_gestores_collection().update_one({"_id": doc["_id"]}, {"$set": fields})
    updated = await get_gestores_collection().find_one({"_id": doc["_id"]})
    if section == "perfil" and updated is not None:
        saved = document_to_gestor_public(updated).model_dump(mode="json")
    return {"updated_at": as_iso(now), "data": saved}
