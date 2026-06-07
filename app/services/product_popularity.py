from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import UpdateOne

from app.database import get_catalog_products_collection

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
    delta = POPULARITY_DELTA[event]
    product_oid = _parse_product_oid(product_id)

    result = await get_catalog_products_collection().update_one(
        {"_id": product_oid},
        {"$inc": {"popularity": delta}},
    )
    if result.matched_count == 0:
        raise ValueError("Producto no encontrado.")


async def bump_products_on_order_completed(items: list[dict[str, Any]]) -> None:
    if not items:
        return

    seen: set[str] = set()
    operations: list[UpdateOne] = []
    delta = POPULARITY_DELTA["purchase"]

    for item in items:
        product_id = str(item.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue

        try:
            product_oid = ObjectId(product_id)
        except InvalidId:
            continue

        seen.add(product_id)
        operations.append(
            UpdateOne({"_id": product_oid}, {"$inc": {"popularity": delta}}),
        )

    if operations:
        await get_catalog_products_collection().bulk_write(operations, ordered=False)
