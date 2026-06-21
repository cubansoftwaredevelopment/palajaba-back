"""Repara productos cuyo category_id impide ver el catálogo público de la tienda."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.config import settings
from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.utils.store_slug import store_name_to_slug

logger = logging.getLogger(__name__)


@dataclass
class StoreCatalogRepairResult:
    seller_id: str
    store_slug: str | None = None
    store_name: str | None = None
    fixed_null_category: int = 0
    fixed_orphan_category: int = 0
    fixed_string_category: int = 0
    fixed_seller_id_type: int = 0
    skipped_no_categories: int = 0

    @property
    def total_fixed(self) -> int:
        return (
            self.fixed_null_category
            + self.fixed_orphan_category
            + self.fixed_string_category
            + self.fixed_seller_id_type
        )


def _parse_repair_slugs(raw: str) -> list[str]:
    slugs: list[str] = []
    for part in raw.split(","):
        slug = store_name_to_slug(part.strip())
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


async def _seller_product_queries(seller_id: str) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = [{"seller_id": seller_id}]
    try:
        queries.append({"seller_id": ObjectId(seller_id)})
    except InvalidId:
        pass
    return queries


async def _load_known_category_ids(seller_id: str) -> set[Any]:
    categories_col = get_catalog_categories_collection()
    category_docs = await categories_col.find({"seller_id": seller_id}).to_list(length=None)
    known: set[Any] = set()
    for doc in category_docs:
        known.add(doc["_id"])
        known.add(str(doc["_id"]))
    return known


async def _first_local_category(seller_id: str) -> dict[str, Any] | None:
    categories_col = get_catalog_categories_collection()
    docs = (
        await categories_col.find({"seller_id": seller_id})
        .sort("sort_order", 1)
        .limit(1)
        .to_list(length=1)
    )
    return docs[0] if docs else None


def _category_is_known(category_id: Any, known_ids: set[Any]) -> bool:
    if category_id is None:
        return False
    if category_id in known_ids:
        return True
    if isinstance(category_id, ObjectId) and str(category_id) in known_ids:
        return True
    if isinstance(category_id, str):
        try:
            return ObjectId(category_id) in known_ids
        except InvalidId:
            return False
    return False


def _normalize_category_id(category_id: Any) -> ObjectId | None:
    if category_id is None:
        return None
    if isinstance(category_id, ObjectId):
        return category_id
    if isinstance(category_id, str):
        try:
            return ObjectId(category_id.strip())
        except InvalidId:
            return None
    return None


async def repair_seller_catalog_products(
    seller_id: str,
    *,
    store_slug: str | None = None,
    store_name: str | None = None,
) -> StoreCatalogRepairResult:
    products_col = get_catalog_products_collection()
    result = StoreCatalogRepairResult(
        seller_id=seller_id,
        store_slug=store_slug,
        store_name=store_name,
    )

    fallback_category = await _first_local_category(seller_id)
    if fallback_category is None:
        logger.warning(
            "Catálogo: tienda %s sin categorías locales; no se pueden reasignar productos.",
            store_slug or seller_id,
        )
        return result

    fallback_oid = fallback_category["_id"]
    known_ids = await _load_known_category_ids(seller_id)
    seen_product_ids: set[Any] = set()

    for query in await _seller_product_queries(seller_id):
        async for product in products_col.find(query):
            product_oid = product["_id"]
            if product_oid in seen_product_ids:
                continue
            seen_product_ids.add(product_oid)

            updates: dict[str, Any] = {}
            if not isinstance(product.get("seller_id"), str):
                updates["seller_id"] = seller_id
                result.fixed_seller_id_type += 1

            category_id = product.get("category_id")
            normalized = _normalize_category_id(category_id)

            if category_id is None:
                updates["category_id"] = fallback_oid
                result.fixed_null_category += 1
            elif isinstance(category_id, str):
                if normalized is None:
                    updates["category_id"] = fallback_oid
                    result.fixed_orphan_category += 1
                elif not _category_is_known(category_id, known_ids):
                    updates["category_id"] = fallback_oid
                    result.fixed_orphan_category += 1
                elif normalized != category_id:
                    updates["category_id"] = normalized
                    result.fixed_string_category += 1
            elif not _category_is_known(category_id, known_ids):
                updates["category_id"] = fallback_oid
                result.fixed_orphan_category += 1

            if updates:
                await products_col.update_one({"_id": product_oid}, {"$set": updates})

    await _sync_category_product_counts(seller_id)
    return result


async def _sync_category_product_counts(seller_id: str) -> None:
    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()
    category_docs = await categories_col.find({"seller_id": seller_id}).to_list(length=None)
    for category_doc in category_docs:
        category_oid = category_doc["_id"]
        count = await products_col.count_documents(
            {"seller_id": seller_id, "category_id": category_oid}
        )
        await categories_col.update_one(
            {"_id": category_oid},
            {"$set": {"product_count": count}},
        )


async def repair_store_catalog_by_slug(store_slug: str) -> StoreCatalogRepairResult:
    slug = store_name_to_slug(store_slug.strip())
    if not slug:
        raise ValueError("Slug de tienda inválido.")

    registrations = get_registrations_collection()
    seller = await registrations.find_one({"store_slug": slug})
    if seller is None:
        raise ValueError(f"Tienda no encontrada para slug «{slug}».")

    seller_id = str(seller["_id"])
    result = await repair_seller_catalog_products(
        seller_id,
        store_slug=slug,
        store_name=seller.get("store_name"),
    )
    if result.total_fixed:
        logger.info(
            "Catálogo reparado para %s (%s): null=%s huérfanos=%s string=%s seller_id=%s",
            seller.get("store_name"),
            slug,
            result.fixed_null_category,
            result.fixed_orphan_category,
            result.fixed_string_category,
            result.fixed_seller_id_type,
        )
    return result


async def repair_all_store_catalog_products() -> list[StoreCatalogRepairResult]:
    registrations = get_registrations_collection()
    seller_ids = await registrations.distinct("_id")
    results: list[StoreCatalogRepairResult] = []
    for seller_oid in seller_ids:
        seller_id = str(seller_oid)
        seller = await registrations.find_one({"_id": seller_oid})
        result = await repair_seller_catalog_products(
            seller_id,
            store_slug=(seller or {}).get("store_slug"),
            store_name=(seller or {}).get("store_name"),
        )
        if result.total_fixed:
            results.append(result)
    return results


async def ensure_store_catalog_repairs_on_startup() -> None:
    configured_slugs = _parse_repair_slugs(settings.catalog_repair_store_slugs)
    if configured_slugs:
        for slug in configured_slugs:
            try:
                await repair_store_catalog_by_slug(slug)
            except ValueError as exc:
                logger.error("Catálogo: no se pudo reparar %s: %s", slug, exc)
    else:
        results = await repair_all_store_catalog_products()
        if results:
            logger.info(
                "Catálogo: reparación global al arranque en %s tienda(s).",
                len(results),
            )
