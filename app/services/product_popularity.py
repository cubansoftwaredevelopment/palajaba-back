from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import UpdateOne

from app.database import get_catalog_products_collection, get_registrations_collection
from app.services.plans import recommendation_multiplier

PopularityEvent = Literal["view", "jaba"]

POPULARITY_DELTA: dict[PopularityEvent | Literal["purchase"], int] = {
    "view": 1,
    "jaba": 2,
    "purchase": 3,
}

MARKETPLACE_PRODUCT_SORT = [("popularity", -1), ("sort_order", 1), ("name", 1)]


def _parse_product_oid(product_id: str) -> ObjectId:
    try:
        return ObjectId(product_id.strip())
    except InvalidId as exc:
        raise ValueError("Producto no válido.") from exc


async def _seller_recommendation_multiplier(seller_id: str) -> int:
    try:
        seller_oid = ObjectId(seller_id)
    except InvalidId:
        return 1

    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if not seller:
        return 1
    return recommendation_multiplier(seller)


async def ensure_popularity_field() -> None:
    products = get_catalog_products_collection()
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


async def bump_product_popularity(product_id: str, event: PopularityEvent) -> None:
    product_oid = _parse_product_oid(product_id)
    collection = get_catalog_products_collection()
    product = await collection.find_one({"_id": product_oid}, {"seller_id": 1})
    if not product:
        raise ValueError("Producto no encontrado.")

    multiplier = await _seller_recommendation_multiplier(str(product.get("seller_id") or ""))
    delta = POPULARITY_DELTA[event] * multiplier

    await collection.update_one({"_id": product_oid}, {"$inc": {"popularity": delta}})


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

    seller_multipliers: dict[str, int] = {}
    operations: list[UpdateOne] = []

    async for product in products_col.find({"_id": {"$in": product_ids}}, {"seller_id": 1}):
        seller_id = str(product.get("seller_id") or "")
        if seller_id not in seller_multipliers:
            seller_multipliers[seller_id] = await _seller_recommendation_multiplier(seller_id)
        delta = POPULARITY_DELTA["purchase"] * seller_multipliers[seller_id]
        operations.append(UpdateOne({"_id": product["_id"]}, {"$inc": {"popularity": delta}}))

    if operations:
        await products_col.bulk_write(operations, ordered=False)
