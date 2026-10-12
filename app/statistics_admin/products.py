"""Top de productos vendidos y de productos populares en el periodo del admin."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.database import (
    get_catalog_products_collection,
    get_orders_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
)
from app.services.exchange_rates import get_cup_per_unit
from app.services.seller_stats import resolve_comparison_window
from app.statistics_admin.schemas.orders import (
    AdminTopPopularProduct,
    AdminTopPopularProducts,
    AdminTopSoldProduct,
    AdminTopSoldProducts,
    OrdersGranularity,
)
from app.utils.currency_conversion import convert_amount

TOP_PRODUCTS_LIMIT = 20
_DELETED_PRODUCT = "Producto eliminado"


def _ranking_window(
    granularity: OrdersGranularity,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime, str, int | None, int | None]:
    if start is not None and end is not None:
        return start, end, "Rango seleccionado", None, None
    window = resolve_comparison_window(granularity)
    return (
        window.current_start,
        window.current_end,
        window.period_label,
        window.current_start.year,
        window.current_start.month,
    )


def _object_ids(values: list[str]) -> list[ObjectId]:
    parsed: list[ObjectId] = []
    for value in values:
        try:
            parsed.append(ObjectId(value))
        except (InvalidId, TypeError):
            continue
    return parsed


def _cup_amount(amount: float, currency: str) -> float | None:
    code = currency.strip().upper()
    if not code:
        return None
    if code != "CUP" and not get_cup_per_unit().get(code):
        return None
    try:
        return float(convert_amount(float(amount), code, "CUP"))
    except (TypeError, ValueError):
        return None


async def _catalog_by_id(product_ids: list[str]) -> dict[str, dict[str, Any]]:
    object_ids = _object_ids(product_ids)
    if not object_ids:
        return {}
    found: dict[str, dict[str, Any]] = {}
    async for doc in get_catalog_products_collection().find(
        {"_id": {"$in": object_ids}},
        projection={"name": 1, "seller_id": 1},
    ):
        found[str(doc["_id"])] = doc
    return found


async def _stores_by_seller(seller_ids: list[str]) -> dict[str, str]:
    object_ids = _object_ids(seller_ids)
    if not object_ids:
        return {}
    found: dict[str, str] = {}
    async for seller in get_registrations_collection().find(
        {"_id": {"$in": object_ids}},
        projection={"store_name": 1},
    ):
        name = str(seller.get("store_name") or "").strip()
        if name:
            found[str(seller["_id"])] = name
    return found


async def get_top_sold_products(
    *,
    granularity: OrdersGranularity,
    start: datetime | None = None,
    end: datetime | None = None,
) -> AdminTopSoldProducts:
    range_start, range_end, period_label, year, month = _ranking_window(granularity, start, end)
    rows = await get_orders_collection().aggregate(
        [
            {
                "$match": {
                    "status": "completed",
                    "completed_at": {"$gte": range_start, "$lt": range_end},
                }
            },
            {"$unwind": "$items"},
            {
                "$group": {
                    "_id": {
                        "product_id": "$items.product_id",
                        "currency": {"$toUpper": {"$ifNull": ["$items.currency", ""]}},
                    },
                    "name": {"$last": "$items.name"},
                    "seller_id": {"$first": "$seller_id"},
                    "store_name": {"$first": "$store_name"},
                    "quantity": {"$sum": {"$ifNull": ["$items.quantity", 0]}},
                    "amount": {
                        "$sum": {
                            "$multiply": [
                                {"$ifNull": ["$items.unit_price", 0]},
                                {"$ifNull": ["$items.quantity", 0]},
                            ]
                        }
                    },
                }
            },
        ]
    ).to_list(length=None)

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("_id") or {}
        product_id = str(key.get("product_id") or "").strip()
        if not product_id:
            continue
        bucket = merged.setdefault(
            product_id,
            {
                "product_id": product_id,
                "name": str(row.get("name") or "Producto").strip() or "Producto",
                "seller_id": str(row.get("seller_id") or ""),
                "store_name": str(row.get("store_name") or "Tienda").strip() or "Tienda",
                "quantity": 0,
                "amount_cup": 0.0,
                "has_amount": False,
            },
        )
        bucket["quantity"] += int(row.get("quantity") or 0)
        if row.get("name"):
            bucket["name"] = str(row["name"]).strip() or bucket["name"]
        converted = _cup_amount(float(row.get("amount") or 0), str(key.get("currency") or ""))
        if converted is not None:
            bucket["amount_cup"] += converted
            bucket["has_amount"] = True

    catalog = await _catalog_by_id(list(merged))
    stores = await _stores_by_seller([item["seller_id"] for item in merged.values()])
    for product_id, bucket in merged.items():
        product = catalog.get(product_id)
        if product and str(product.get("name") or "").strip():
            bucket["name"] = str(product["name"]).strip()
        store_name = stores.get(bucket["seller_id"])
        if store_name:
            bucket["store_name"] = store_name

    ranked = sorted(merged.values(), key=lambda item: (-int(item["quantity"]), item["name"].casefold()))
    total_units = sum(int(item["quantity"]) for item in ranked)
    products = [
        AdminTopSoldProduct(
            product_id=item["product_id"],
            name=item["name"],
            store_name=item["store_name"],
            quantity=int(item["quantity"]),
            amount_cup=float(item["amount_cup"]) if item["has_amount"] else None,
        )
        for item in ranked[:TOP_PRODUCTS_LIMIT]
    ]
    return AdminTopSoldProducts(
        granularity=granularity,
        year=year,
        month=month,
        period_label=period_label,
        total_units=total_units,
        products=products,
    )


async def get_top_popular_products(
    *,
    granularity: OrdersGranularity,
    start: datetime | None = None,
    end: datetime | None = None,
) -> AdminTopPopularProducts:
    range_start, range_end, period_label, year, month = _ranking_window(granularity, start, end)
    rows = await get_product_popularity_events_collection().aggregate(
        [
            {"$match": {"created_at": {"$gte": range_start, "$lt": range_end}}},
            {
                "$group": {
                    "_id": "$product_id",
                    "seller_id": {"$first": "$seller_id"},
                    "points": {"$sum": {"$ifNull": ["$points", 0]}},
                    "views": {"$sum": {"$cond": [{"$eq": ["$event", "view"]}, 1, 0]}},
                    "jaba": {"$sum": {"$cond": [{"$eq": ["$event", "jaba"]}, 1, 0]}},
                    "purchases": {"$sum": {"$cond": [{"$eq": ["$event", "purchase"]}, 1, 0]}},
                }
            },
        ]
    ).to_list(length=None)

    catalog = await _catalog_by_id([str(row.get("_id") or "") for row in rows])
    stores = await _stores_by_seller([str(row.get("seller_id") or "") for row in rows])
    ranked_rows: list[dict[str, Any]] = []
    for row in rows:
        product_id = str(row.get("_id") or "").strip()
        if not product_id:
            continue
        product = catalog.get(product_id)
        seller_id = str(row.get("seller_id") or "")
        catalog_name = str(product.get("name") or "").strip() if product else ""
        ranked_rows.append(
            {
                "product_id": product_id,
                "name": catalog_name or _DELETED_PRODUCT,
                "store_name": stores.get(seller_id) or "Tienda",
                "points": int(row.get("points") or 0),
                "views": int(row.get("views") or 0),
                "jaba": int(row.get("jaba") or 0),
                "purchases": int(row.get("purchases") or 0),
            }
        )

    ranked_rows.sort(key=lambda item: (-item["points"], item["name"].casefold()))
    total_points = sum(item["points"] for item in ranked_rows)
    products = [AdminTopPopularProduct(**item) for item in ranked_rows[:TOP_PRODUCTS_LIMIT]]
    return AdminTopPopularProducts(
        granularity=granularity,
        year=year,
        month=month,
        period_label=period_label,
        total_points=total_points,
        products=products,
    )
