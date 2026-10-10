import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import UpdateOne

from app.database import (
    get_catalog_products_collection,
    get_product_popularity_events_collection,
    get_registrations_collection,
)
from app.services.plans import PREMIUM_RECOMMENDATION_MULTIPLIER, recommendation_multiplier
from app.utils.datetime import to_utc_naive, utc_now

PopularityEvent = Literal["view", "jaba", "purchase"]

POPULARITY_DELTA: dict[PopularityEvent, int] = {
    "view": 1,
    "jaba": 2,
    "purchase": 3,
}

POPULARITY_WINDOW = timedelta(weeks=3)
_REFRESH_INTERVAL_SECONDS = 30.0

MARKETPLACE_PRODUCT_SORT = [("popularity", -1), ("sort_order", 1), ("name", 1)]

_refresh_lock = asyncio.Lock()
_last_refresh_monotonic = 0.0


def popularity_cutoff(now: datetime | None = None) -> datetime:
    moment = to_utc_naive(now or utc_now())
    return moment - POPULARITY_WINDOW


def popularity_score(points: int, *, premium: bool) -> int:
    total = max(0, int(points))
    if premium:
        return total * PREMIUM_RECOMMENDATION_MULTIPLIER
    return total


def _parse_product_oid(product_id: str) -> ObjectId:
    try:
        return ObjectId(product_id.strip())
    except InvalidId as exc:
        raise ValueError("Producto no válido.") from exc


def _score_for_seller(points: int, seller: dict[str, Any] | None) -> int:
    premium = bool(seller) and recommendation_multiplier(seller) > 1
    return popularity_score(points, premium=premium)


async def ensure_popularity_field() -> None:
    products = get_catalog_products_collection()
    events = get_product_popularity_events_collection()
    await products.update_many(
        {"popularity": {"$exists": False}},
        {"$set": {"popularity": 0}},
    )
    await products.create_index(
        [
            ("global_category_id", 1),
            ("is_available", 1),
            ("popularity", -1),
            ("sort_order", 1),
        ],
        name="marketplace_category_popularity",
    )
    await events.create_index(
        [("product_id", 1), ("created_at", -1)],
        name="product_popularity_events_by_product",
    )
    await events.create_index(
        [("created_at", -1)],
        name="product_popularity_events_by_time",
    )
    await events.create_index(
        [("seller_id", 1)],
        name="product_popularity_events_by_seller",
    )


async def _window_points_by_product(product_ids: list[str] | None) -> dict[str, int]:
    match: dict[str, Any] = {"created_at": {"$gte": popularity_cutoff()}}
    if product_ids is not None:
        match["product_id"] = {"$in": product_ids}

    rows = await get_product_popularity_events_collection().aggregate(
        [
            {"$match": match},
            {"$group": {"_id": "$product_id", "points": {"$sum": "$points"}}},
        ]
    ).to_list(length=None)
    return {str(row["_id"]): int(row.get("points") or 0) for row in rows}


async def _seller_docs_by_id(seller_ids: set[str]) -> dict[str, dict[str, Any]]:
    object_ids: list[ObjectId] = []
    for seller_id in seller_ids:
        try:
            object_ids.append(ObjectId(seller_id))
        except InvalidId:
            continue
    if not object_ids:
        return {}

    docs = await get_registrations_collection().find(
        {"_id": {"$in": object_ids}},
        {"plan_tier": 1},
    ).to_list(length=None)
    return {str(doc["_id"]): doc for doc in docs}


async def _write_scores(
    product_ids: list[str] | None,
    points_by_product: dict[str, int],
) -> None:
    products_col = get_catalog_products_collection()
    if product_ids is None:
        query: dict[str, Any] = {"_id": {"$in": []}}
        object_ids: list[ObjectId] = []
        for product_id in points_by_product:
            try:
                object_ids.append(ObjectId(product_id))
            except InvalidId:
                continue
        if object_ids:
            query = {"_id": {"$in": object_ids}}
        else:
            await products_col.update_many(
                {"popularity": {"$gt": 0}},
                {"$set": {"popularity": 0}},
            )
            return
    else:
        object_ids = []
        for product_id in product_ids:
            try:
                object_ids.append(ObjectId(product_id))
            except InvalidId:
                continue
        if not object_ids:
            return
        query = {"_id": {"$in": object_ids}}

    product_docs = await products_col.find(query, {"seller_id": 1}).to_list(length=None)
    sellers = await _seller_docs_by_id(
        {str(doc.get("seller_id") or "") for doc in product_docs if doc.get("seller_id")}
    )

    operations: list[UpdateOne] = []
    scored_ids: list[ObjectId] = []
    for doc in product_docs:
        product_id = str(doc["_id"])
        seller = sellers.get(str(doc.get("seller_id") or ""))
        score = _score_for_seller(points_by_product.get(product_id, 0), seller)
        operations.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"popularity": score}}))
        scored_ids.append(doc["_id"])

    if operations:
        await products_col.bulk_write(operations, ordered=False)

    if product_ids is None:
        stale_filter: dict[str, Any] = {"popularity": {"$gt": 0}}
        if scored_ids:
            stale_filter["_id"] = {"$nin": scored_ids}
        await products_col.update_many(stale_filter, {"$set": {"popularity": 0}})


async def recalculate_products_popularity(product_ids: list[str]) -> None:
    if not product_ids:
        return
    async with _refresh_lock:
        points = await _window_points_by_product(product_ids)
        await _write_scores(product_ids, points)


async def refresh_popularity_window() -> None:
    """Recalcula el puntaje guardado con los eventos de las últimas 3 semanas."""
    global _last_refresh_monotonic
    now = time.monotonic()
    if now - _last_refresh_monotonic < _REFRESH_INTERVAL_SECONDS:
        return

    async with _refresh_lock:
        now = time.monotonic()
        if now - _last_refresh_monotonic < _REFRESH_INTERVAL_SECONDS:
            return
        points = await _window_points_by_product(None)
        await _write_scores(None, points)
        _last_refresh_monotonic = time.monotonic()


async def _insert_event(product: dict[str, Any], event: PopularityEvent) -> None:
    await get_product_popularity_events_collection().insert_one(
        {
            "product_id": str(product["_id"]),
            "seller_id": str(product.get("seller_id") or ""),
            "event": event,
            "points": POPULARITY_DELTA[event],
            "created_at": to_utc_naive(utc_now()),
        }
    )
    await recalculate_products_popularity([str(product["_id"])])


async def bump_product_popularity(product_id: str, event: PopularityEvent) -> None:
    product_oid = _parse_product_oid(product_id)
    product = await get_catalog_products_collection().find_one(
        {"_id": product_oid},
        {"seller_id": 1},
    )
    if not product:
        raise ValueError("Producto no encontrado.")
    await _insert_event(product, event)


async def bump_products_on_order_completed(items: list[dict[str, Any]]) -> None:
    if not items:
        return

    products_col = get_catalog_products_collection()
    seen: set[str] = set()
    product_ids: list[ObjectId] = []

    for item in items:
        product_id = str(item.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        try:
            product_ids.append(ObjectId(product_id))
        except InvalidId:
            continue
        seen.add(product_id)

    if not product_ids:
        return

    now = to_utc_naive(utc_now())
    events = get_product_popularity_events_collection()
    documents: list[dict[str, Any]] = []
    recalculate_ids: list[str] = []

    async for product in products_col.find({"_id": {"$in": product_ids}}, {"seller_id": 1}):
        product_id = str(product["_id"])
        documents.append(
            {
                "product_id": product_id,
                "seller_id": str(product.get("seller_id") or ""),
                "event": "purchase",
                "points": POPULARITY_DELTA["purchase"],
                "created_at": now,
            }
        )
        recalculate_ids.append(product_id)

    if documents:
        await events.insert_many(documents, ordered=False)
        await recalculate_products_popularity(recalculate_ids)


async def delete_popularity_events_for_products(product_ids: list[str]) -> None:
    ids = [product_id for product_id in product_ids if product_id]
    if not ids:
        return
    await get_product_popularity_events_collection().delete_many({"product_id": {"$in": ids}})


async def delete_popularity_events_for_seller(seller_id: str) -> None:
    if not seller_id:
        return
    await get_product_popularity_events_collection().delete_many({"seller_id": seller_id})
