"""Fechas y guardado de las secciones del cliente."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.account_sync.compare import as_iso, newest, section_clock, section_verdict, verdicts_for
from app.database import (
    get_customer_notifications_collection,
    get_customers_collection,
    get_orders_collection,
)
from app.utils.datetime import to_utc_naive, utc_now

SECTIONS = ("perfil", "direcciones", "favoritos", "pedidos", "avisos")


def _now() -> datetime:
    return to_utc_naive(utc_now())


async def touch_customer(customer_id: str, *sections: str) -> datetime:
    now = _now()
    fields: dict[str, Any] = {"updated_at": now}
    for name in sections:
        if name in SECTIONS:
            fields[f"section_updated_at.{name}"] = now
    await get_customers_collection().update_one({"_id": ObjectId(customer_id)}, {"$set": fields})
    return now


async def _customer(customer_id: str) -> dict[str, Any]:
    doc = await get_customers_collection().find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    return doc


def _fallback(doc: dict[str, Any], name: str) -> datetime | None:
    clock = section_clock(doc, name)
    if clock is not None:
        return clock
    if name in ("perfil", "direcciones", "favoritos"):
        created = doc.get("created_at")
        if isinstance(created, datetime):
            return to_utc_naive(created)
    return None


async def _latest(collection, query: dict[str, Any], field: str) -> datetime | None:
    doc = await collection.find_one(query, {field: 1}, sort=[(field, -1)])
    if not doc:
        return None
    value = doc.get(field)
    return to_utc_naive(value) if isinstance(value, datetime) else None


async def server_dates(customer_id: str) -> dict[str, datetime | None]:
    doc = await _customer(customer_id)
    orders = get_orders_collection()
    notices = get_customer_notifications_collection()
    buyer = {"buyer_id": customer_id}
    notice_query = {"customer_id": {"$in": [customer_id, ObjectId(customer_id)]}}
    return {
        "perfil": _fallback(doc, "perfil"),
        "direcciones": _fallback(doc, "direcciones"),
        "favoritos": _fallback(doc, "favoritos"),
        "pedidos": newest(section_clock(doc, "pedidos"), await _latest(orders, buyer, "updated_at")),
        "avisos": newest(
            section_clock(doc, "avisos"),
            await _latest(notices, notice_query, "created_at"),
            await _latest(notices, notice_query, "read_at"),
        ),
    }


async def compare_customer(customer_id: str, phone_dates: dict[str, Any]) -> dict[str, bool | None]:
    return verdicts_for(await server_dates(customer_id), phone_dates)


def _require_newer(phone_raw: Any, server_at: datetime | None) -> None:
    if section_verdict(phone_raw, server_at) is not True:
        raise HTTPException(status_code=409, detail="El servidor tiene una copia más reciente de esta sección.")


def _addresses(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="Las direcciones no son válidas.")
    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Las direcciones no son válidas.")
        label = " ".join(str(item.get("label") or "").split())
        address = " ".join(str(item.get("address") or "").split())
        if not label or len(address) < 3:
            raise HTTPException(status_code=422, detail="Cada dirección necesita nombre y dirección.")
        row: dict[str, Any] = {"id": str(item.get("id") or uuid.uuid4()), "label": label[:48], "address": address[:300]}
        if item.get("latitude") is not None and item.get("longitude") is not None:
            row["latitude"] = float(item["latitude"])
            row["longitude"] = float(item["longitude"])
        cleaned.append(row)
    return cleaned


async def apply_customer_section(customer_id: str, section: str, updated_at: Any, data: Any) -> dict[str, Any]:
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Esa sección no existe.")
    dates = await server_dates(customer_id)
    _require_newer(updated_at, dates[section])
    now = _now()
    customers = get_customers_collection()
    oid = ObjectId(customer_id)
    if section == "perfil":
        if not isinstance(data, dict):
            raise HTTPException(status_code=422, detail="El perfil no es válido.")
        full_name = " ".join(str(data.get("full_name") or "").split())
        if len(full_name) < 2 or len(full_name) > 120:
            raise HTTPException(status_code=422, detail="El nombre debe tener entre 2 y 120 caracteres.")
        fields: dict[str, Any] = {"full_name": full_name, "updated_at": now, "section_updated_at.perfil": now}
        if "qvapay_prompt_dismissed" in data:
            fields["qvapay_prompt_dismissed"] = bool(data["qvapay_prompt_dismissed"])
        await customers.update_one({"_id": oid}, {"$set": fields})
        saved = {"full_name": full_name, "qvapay_prompt_dismissed": bool(data.get("qvapay_prompt_dismissed"))}
    elif section == "direcciones":
        rows = _addresses(data)
        await customers.update_one(
            {"_id": oid},
            {"$set": {"addresses": rows, "updated_at": now, "section_updated_at.direcciones": now}},
        )
        saved = rows
    elif section == "favoritos":
        if not isinstance(data, dict):
            raise HTTPException(status_code=422, detail="Los favoritos no son válidos.")
        ids: list[str] = []
        for raw in data.get("favorite_product_ids") or []:
            key = str(raw or "").strip()
            if key and key not in ids:
                ids.append(key)
        favorites = [item for item in (data.get("favorites") or []) if isinstance(item, dict) and item.get("id")]
        await customers.update_one(
            {"_id": oid},
            {"$set": {
                "favorite_product_ids": ids,
                "favorites": favorites,
                "updated_at": now,
                "section_updated_at.favoritos": now,
            }},
        )
        saved = {"favorite_product_ids": ids, "favorites": favorites}
    elif section == "avisos":
        items = data if isinstance(data, list) else (data or {}).get("items") if isinstance(data, dict) else []
        notices = get_customer_notifications_collection()
        for item in items or []:
            if not isinstance(item, dict) or not item.get("id") or not item.get("read_at"):
                continue
            try:
                notice_id = ObjectId(str(item["id"]))
            except Exception:
                continue
            read_at = parse_read(item.get("read_at")) or now
            await notices.update_one(
                {"_id": notice_id, "customer_id": {"$in": [customer_id, oid]}, "read_at": {"$in": [None, ""]}},
                {"$set": {"read_at": read_at}},
            )
        await customers.update_one({"_id": oid}, {"$set": {"section_updated_at.avisos": now, "updated_at": now}})
        saved = {"read": True}
    else:
        await customers.update_one({"_id": oid}, {"$set": {"section_updated_at.pedidos": now, "updated_at": now}})
        saved = {"kept": True}
    return {"updated_at": as_iso(now), "data": saved}


def parse_read(value: Any) -> datetime | None:
    from app.account_sync.compare import parse_phone_date

    return parse_phone_date(value)
