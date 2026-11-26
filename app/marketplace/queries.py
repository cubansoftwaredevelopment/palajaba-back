"""Consultas de productos del marketplace y del catálogo."""

from typing import Any
from bson import ObjectId
from bson.errors import InvalidId
from app.database import get_catalog_categories_collection, get_catalog_products_collection
from app.products.sales_areas import sales_area_match_clause
from app.categories.service import business_category_source_ids, normalize_business_category_id
from app.products.utils import (
    MARKETPLACE_PRODUCT_SORT,
    mongo_sort_for_product_mode,
    sort_product_docs,
)
from app.marketplace.sellers import _qvapay_seller_ids, _seller_has_qvapay
from app.marketplace.utils import (
    _and_match,
    _equivalent_currencies,
    _normalize_display_currencies,
    _search_text_filter,
    _selected_sales_area_municipality_ids,
)

def _currency_acceptance_clause(currency: str | list[str] | None) -> dict[str, Any] | None:
    currencies = _equivalent_currencies(_normalize_display_currencies(currency))
    if not currencies:
        return None
    if len(currencies) == 1:
        code = currencies[0]
        return {
            "$or": [
                {"base_currency": code},
                {"accepted_currencies": code},
            ]
        }
    return {
        "$or": [
            {"base_currency": {"$in": currencies}},
            {"accepted_currencies": {"$in": currencies}},
        ]
    }

def _display_currency_clause(
    currency: str | list[str] | None,
    qvapay_seller_ids: list[str],
) -> dict[str, Any] | None:
    """QUSD no es otra moneda del producto: deja solo tiendas con usuario QvaPay."""
    codes = _normalize_display_currencies(currency)
    if not codes:
        return None
    wants_qusd = "QUSD" in codes
    others = [code for code in codes if code != "QUSD"]
    parts: list[dict[str, Any]] = []
    if others:
        other_clause = _currency_acceptance_clause(others)
        if other_clause:
            parts.append(other_clause)
    if wants_qusd:
        parts.append({"seller_id": {"$in": qvapay_seller_ids}})
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$or": parts}

def _and_currency(
    query: dict[str, Any],
    currency: str | list[str] | None,
    qvapay_seller_ids: list[str] | None = None,
) -> dict[str, Any]:
    return _and_match(query, _display_currency_clause(currency, qvapay_seller_ids or []))

def _listable_product_match() -> dict[str, Any]:
    return {
        "$or": [
            {"is_available": True, "view_only": {"$ne": True}},
            {"view_only": True},
        ]
    }

async def _count_products_by_seller(
    seller_ids: list[str],
    extra_clause: dict[str, Any] | None = None,
) -> dict[str, int]:
    if not seller_ids:
        return {}
    match_parts: list[dict[str, Any]] = [
        {"seller_id": {"$in": seller_ids}},
        _listable_product_match(),
        {"deleted_at": None},
    ]
    if extra_clause:
        match_parts.append(extra_clause)
    docs = await get_catalog_products_collection().aggregate(
        [
            {"$match": {"$and": match_parts}},
            {"$group": {"_id": "$seller_id", "count": {"$sum": 1}}},
        ]
    ).to_list(length=None)
    return {str(doc["_id"]): int(doc.get("count") or 0) for doc in docs if doc.get("_id")}

async def _seller_acceptance_counts(
    seller_ids: list[str],
    currency: str | list[str] | None,
) -> dict[str, int] | None:
    """None si no hay filtro. QUSD cuenta las tiendas con usuario QvaPay."""
    codes = _normalize_display_currencies(currency)
    if not codes:
        return None
    if not seller_ids:
        return {}
    wants_qusd = "QUSD" in codes
    others = [code for code in codes if code != "QUSD"]
    counts: dict[str, int] = {}
    if others:
        counts.update(await _count_products_by_seller(seller_ids, _currency_acceptance_clause(others)))
    if wants_qusd:
        qvapay_ids = await _qvapay_seller_ids(seller_ids)
        for seller_id, count in (await _count_products_by_seller(qvapay_ids)).items():
            counts[seller_id] = count
    return counts

def _marketplace_product_query(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    province_id: str | None = None,
    municipality_id: str | None = None,
    sales_area_municipality_ids: list[str] | None = None,
) -> dict[str, Any]:
    visibility: list[dict[str, Any]] = []
    if local_seller_ids:
        visibility.append({"seller_id": {"$in": local_seller_ids}})
    if delivery_seller_ids:
        visibility.append({"seller_id": {"$in": delivery_seller_ids}})
    if pickup_seller_ids:
        visibility.append({"seller_id": {"$in": pickup_seller_ids}})
    if not visibility:
        return {"_id": {"$exists": False}}

    query: dict[str, Any] = {
        "is_available": True,
        "view_only": {"$ne": True},
        "deleted_at": None,
        "$or": visibility,
    }
    if extra:
        query.update(extra)
    if province_id and municipality_id:
        selected_municipalities = list(dict.fromkeys(
            [municipality_id, *(sales_area_municipality_ids or [])]
        ))
        query = _and_match(query, sales_area_match_clause(province_id, selected_municipalities))
    return query

def _seller_store_product_query(
    seller_id: str,
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
    *,
    currency: str | None = None,
    extra: dict[str, Any] | None = None,
    municipios_adicionales: list[str] | None = None,
) -> dict[str, Any]:
    """Catálogo público de una tienda: incluye agotados; el marketplace usa otra query."""
    query: dict[str, Any] = {"seller_id": seller_id, "deleted_at": None}
    if extra:
        query.update(extra)
    if province_id and municipality_id:
        selected_ids = _selected_sales_area_municipality_ids(
            province_id,
            municipality_id,
            municipios_adicionales,
        )
        query = _and_match(query, sales_area_match_clause(province_id, selected_ids))
    qvapay_ids = [seller_id] if _seller_has_qvapay(seller) else []
    return _and_currency(query, currency, qvapay_ids)

def _extra_buyer_municipality_ids(
    province_id: str,
    municipality_id: str,
    municipios_adicionales: list[str] | None,
) -> list[str]:
    selected_ids = _selected_sales_area_municipality_ids(
        province_id,
        municipality_id,
        municipios_adicionales,
    )
    return [item for item in selected_ids if item != municipality_id]

async def _store_catalog_category_docs(
    seller_id: str,
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
    *,
    currency: str | None = None,
    municipios_adicionales: list[str] | None = None,
) -> list[dict[str, Any]]:
    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    category_docs = await categories_col.find({"seller_id": seller_id}).sort("sort_order", 1).to_list(length=None)
    if category_docs:
        known_ids = {doc["_id"] for doc in category_docs}
        base_query = _seller_store_product_query(
            seller_id,
            seller,
            province_id,
            municipality_id,
            currency=currency,
            municipios_adicionales=municipios_adicionales,
        )
        orphan_category_ids = await products_col.distinct("category_id", base_query)
        for category_oid in orphan_category_ids:
            if category_oid is None or category_oid in known_ids:
                continue
            category_docs.append(
                {
                    "_id": category_oid,
                    "seller_id": seller_id,
                    "name": "Otros",
                    "sort_order": 9999,
                }
            )
        return category_docs

    if await products_col.count_documents(
        _seller_store_product_query(
            seller_id,
            seller,
            province_id,
            municipality_id,
            currency=currency,
            municipios_adicionales=municipios_adicionales,
        )
    ) <= 0:
        return []

    return [
        {
            "_id": None,
            "seller_id": seller_id,
            "name": "Catálogo",
            "sort_order": 0,
        }
    ]

async def _build_marketplace_products_query(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
    global_category_id: str | None = None,
    search_text: str | None = None,
    currency: str | None = None,
    province_id: str | None = None,
    municipality_id: str | None = None,
    sales_area_municipality_ids: list[str] | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if global_category_id:
        canonical_id = normalize_business_category_id(global_category_id)
        source_ids = business_category_source_ids(canonical_id)
        extra["global_category_id"] = source_ids[0] if len(source_ids) == 1 else {"$in": source_ids}

    query = _marketplace_product_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids,
        extra=extra or None,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )
    if query.get("_id"):
        return query

    text_filter = _search_text_filter(search_text or "")
    if text_filter:
        query = {"$and": [query, text_filter]}
    seller_ids = list(dict.fromkeys([
        *local_seller_ids,
        *delivery_seller_ids,
        *(pickup_seller_ids or []),
    ]))
    codes = _normalize_display_currencies(currency) or []
    qvapay_ids = await _qvapay_seller_ids(seller_ids) if "QUSD" in codes else []
    return _and_currency(query, currency, qvapay_ids)

async def _list_category_product_docs(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    global_category_id: str,
    *,
    pickup_seller_ids: list[str] | None = None,
    currency: str | None = None,
    limit: int,
    offset: int,
    province_id: str | None = None,
    municipality_id: str | None = None,
    sales_area_municipality_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    products_col = get_catalog_products_collection()
    query = await _build_marketplace_products_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids,
        global_category_id=global_category_id,
        currency=currency,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )
    if query.get("_id"):
        return []

    cursor = (
        products_col.find(query)
        .sort(MARKETPLACE_PRODUCT_SORT)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)

async def _get_local_category_doc(seller_id: str, category_id: str) -> dict[str, Any]:
    try:
        category_oid = ObjectId(category_id.strip())
    except InvalidId as exc:
        raise ValueError("Categoría no encontrada.") from exc

    category_doc = await get_catalog_categories_collection().find_one(
        {"_id": category_oid, "seller_id": seller_id}
    )
    if category_doc is None:
        raise ValueError("Categoría no encontrada.")
    return category_doc

def _zone_visible_product_query(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    province_id: str | None = None,
    municipality_id: str | None = None,
) -> dict[str, Any]:
    query = _marketplace_product_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids,
        extra=extra,
        province_id=province_id,
        municipality_id=municipality_id,
    )
    if query.get("_id") == {"$exists": False}:
        return query
    query.pop("is_available", None)
    query.pop("view_only", None)
    return query

async def _catalog_product_name(product_id: str) -> str:
    try:
        oid = ObjectId(str(product_id).strip())
    except InvalidId:
        return "Producto"
    doc = await get_catalog_products_collection().find_one({"_id": oid}, {"name": 1})
    name = str((doc or {}).get("name") or "").strip()
    return name or "Producto"

async def _list_store_local_product_docs(
    seller_id: str,
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
    category_doc: dict[str, Any] | None,
    *,
    limit: int,
    offset: int,
    currency: str | None = None,
    extra: dict[str, Any] | None = None,
    municipios_adicionales: list[str] | None = None,
) -> list[dict[str, Any]]:
    products_col = get_catalog_products_collection()
    category_oid = category_doc["_id"] if category_doc else None
    query_extra: dict[str, Any] = {}
    if category_oid is not None:
        query_extra["category_id"] = category_oid
    if extra:
        query_extra.update(extra)
    query = _seller_store_product_query(
        seller_id,
        seller,
        province_id,
        municipality_id,
        currency=currency,
        extra=query_extra or None,
        municipios_adicionales=municipios_adicionales,
    )
    sort_spec = mongo_sort_for_product_mode(
        category_doc.get("product_sort_mode") if category_doc else "popularity",
    )
    mode = category_doc.get("product_sort_mode") if category_doc else "popularity"
    if sort_spec is None:
        product_docs = await products_col.find(query).to_list(length=None)
        sorted_docs = sort_product_docs(product_docs, mode)
        return sorted_docs[offset : offset + limit]

    cursor = (
        products_col.find(query)
        .sort(sort_spec)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)
