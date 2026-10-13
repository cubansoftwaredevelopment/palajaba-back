"""Listado de productos del admin: categoría, negocio, precio y zonas."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.database import get_catalog_products_collection, get_registrations_collection
from app.schemas.admin_products import AdminProductList, AdminProductRow
from app.services.categories import business_category_name


def _area_label(area: dict[str, Any]) -> str | None:
    municipality = str(area.get("municipality_name") or "").strip()
    province = str(area.get("province_name") or "").strip()
    if municipality and province:
        return f"{municipality}, {province}"
    return municipality or province or None


def _locations(seller: dict[str, Any] | None, *, offers_delivery: bool) -> list[str]:
    if not seller:
        return []
    areas: list[dict[str, Any]] = []
    business = seller.get("business_area")
    if isinstance(business, dict):
        areas.append(business)
    if offers_delivery:
        for area in seller.get("delivery_areas") or []:
            if isinstance(area, dict):
                areas.append(area)

    labels: list[str] = []
    seen: set[tuple[str, str]] = set()
    for area in areas:
        label = _area_label(area)
        if not label:
            continue
        key = (str(area.get("province_id") or ""), str(area.get("municipality_id") or label))
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


async def list_admin_products() -> AdminProductList:
    docs = await get_catalog_products_collection().find(
        {},
        projection={
            "name": 1,
            "seller_id": 1,
            "global_category_id": 1,
            "base_price": 1,
            "base_currency": 1,
            "offers_delivery": 1,
        },
    ).to_list(length=None)

    seller_ids: list[ObjectId] = []
    for doc in docs:
        try:
            seller_ids.append(ObjectId(str(doc.get("seller_id") or "")))
        except (InvalidId, TypeError):
            continue

    sellers: dict[str, dict[str, Any]] = {}
    if seller_ids:
        async for seller in get_registrations_collection().find(
            {"_id": {"$in": seller_ids}},
            projection={"store_name": 1, "business_area": 1, "delivery_areas": 1},
        ):
            sellers[str(seller["_id"])] = seller

    rows: list[AdminProductRow] = []
    for doc in docs:
        name = str(doc.get("name") or "").strip()
        if not name:
            continue
        seller = sellers.get(str(doc.get("seller_id") or ""))
        offers_delivery = bool(doc.get("offers_delivery"))
        try:
            price = float(doc.get("base_price") or 0)
        except (TypeError, ValueError):
            price = 0
        rows.append(
            AdminProductRow(
                id=str(doc["_id"]),
                name=name,
                category_name=business_category_name(str(doc.get("global_category_id") or "")),
                store_name=str((seller or {}).get("store_name") or "Tienda").strip() or "Tienda",
                price=price,
                currency=str(doc.get("base_currency") or "CUP").strip().upper() or "CUP",
                offers_delivery=offers_delivery,
                locations=_locations(seller, offers_delivery=offers_delivery),
            )
        )

    rows.sort(key=lambda row: (row.name.casefold(), row.store_name.casefold()))
    return AdminProductList(products=rows, total=len(rows))
