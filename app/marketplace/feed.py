"""Feed de inicio, pistas de disponibilidad y productos por categoría."""

from typing import Any
from app.database import get_catalog_products_collection
from app.marketplace.schemas import (
    MarketplaceBusinessPublic,
    MarketplaceCategoryProductsPublic,
    MarketplaceCategorySectionPublic,
    MarketplaceAvailabilityHintsPublic,
    MarketplaceCategoryHint,
    MarketplaceHomeFeedPublic,
)
from app.categories.service import (
    business_category_sort_order,
    business_category_source_ids,
    normalize_business_category_id,
)
from app.products.utils import refresh_popularity_window
from app.subscriptions.service import plan_search_rank
from app.marketplace.businesses import _business_to_public
from app.marketplace.products import _product_to_public
from app.marketplace.queries import (
    _and_currency,
    _list_category_product_docs,
    _marketplace_product_query,
)
from app.marketplace.sellers import (
    _build_marketplace_seller_context,
    _qvapay_seller_ids,
    _seller_has_qvapay,
    _seller_is_local_to_municipality,
)
from app.marketplace.utils import (
    DEFAULT_PAGE_SIZE,
    _display_category_name,
    _equivalent_currencies,
    _normalize_display_currencies,
    _normalize_marketplace_category_id,
    _normalize_page_size,
    _product_currency_codes,
    _selected_sales_area_municipality_ids,
    _validate_location_ids,
)

async def _aggregate_category_stats(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
    currency: str | None = None,
    province_id: str | None = None,
    municipality_id: str | None = None,
    sales_area_municipality_ids: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    seller_ids = list(dict.fromkeys([
        *local_seller_ids,
        *delivery_seller_ids,
        *(pickup_seller_ids or []),
    ]))
    codes = _normalize_display_currencies(currency) or []
    qvapay_ids = await _qvapay_seller_ids(seller_ids) if "QUSD" in codes else []
    match_query = _and_currency(
        _marketplace_product_query(
            local_seller_ids,
            delivery_seller_ids,
            pickup_seller_ids=pickup_seller_ids,
            province_id=province_id,
            municipality_id=municipality_id,
            sales_area_municipality_ids=sales_area_municipality_ids,
        ),
        currency,
        qvapay_ids,
    )
    if match_query.get("_id"):
        return {}

    products_col = get_catalog_products_collection()
    pipeline = [
        {"$match": match_query},
        {
            "$group": {
                "_id": {"$ifNull": ["$global_category_id", "otros"]},
                "count": {"$sum": 1},
                "popularity": {"$sum": {"$ifNull": ["$popularity", 0]}},
            }
        },
    ]
    results = await products_col.aggregate(pipeline).to_list(length=None)
    merged: dict[str, dict[str, int]] = {}
    for item in results:
        raw_id = str(item["_id"])
        canonical_id = normalize_business_category_id(raw_id)
        bucket = merged.setdefault(canonical_id, {"count": 0, "popularity": 0})
        bucket["count"] += int(item["count"])
        bucket["popularity"] += int(item.get("popularity") or 0)
    return merged

FEED_STORES_PER_CATEGORY = 24

async def _stores_by_category(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    category_ids: list[str],
    seller_by_id: dict[str, dict[str, Any]],
    *,
    pickup_seller_ids: list[str] | None = None,
    currency: str | None = None,
    province_id: str,
    municipality_id: str,
    sales_area_municipality_ids: list[str] | None = None,
) -> dict[str, list[MarketplaceBusinessPublic]]:
    if not category_ids:
        return {}

    seller_ids = list(dict.fromkeys([
        *local_seller_ids,
        *delivery_seller_ids,
        *(pickup_seller_ids or []),
    ]))
    codes = _normalize_display_currencies(currency) or []
    qvapay_ids = await _qvapay_seller_ids(seller_ids) if "QUSD" in codes else []
    match_query = _and_currency(
        _marketplace_product_query(
            local_seller_ids,
            delivery_seller_ids,
            pickup_seller_ids=pickup_seller_ids,
            province_id=province_id,
            municipality_id=municipality_id,
            sales_area_municipality_ids=sales_area_municipality_ids,
        ),
        currency,
        qvapay_ids,
    )
    if match_query.get("_id"):
        return {}

    wanted = set(category_ids)
    sources: list[str] = []
    for category_id in category_ids:
        for source_id in business_category_source_ids(category_id):
            if source_id not in sources:
                sources.append(source_id)
    category_filter: dict[str, Any] = {"global_category_id": {"$in": sources}}
    if "otros" in wanted:
        category_filter = {
            "$or": [
                {"global_category_id": {"$in": sources}},
                {"global_category_id": None},
                {"global_category_id": {"$exists": False}},
            ]
        }

    pipeline = [
        {"$match": match_query},
        {"$match": category_filter},
        {
            "$group": {
                "_id": {
                    "category": {"$ifNull": ["$global_category_id", "otros"]},
                    "seller_id": "$seller_id",
                },
                "count": {"$sum": 1},
                "popularity": {"$sum": {"$ifNull": ["$popularity", 0]}},
            }
        },
    ]
    rows = await get_catalog_products_collection().aggregate(pipeline).to_list(length=None)
    grouped: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        identity = row.get("_id") or {}
        category_id = normalize_business_category_id(str(identity.get("category") or "otros"))
        if category_id not in wanted:
            continue
        seller_id = str(identity.get("seller_id") or "")
        if not seller_id or seller_id not in seller_by_id:
            continue
        bucket = grouped.setdefault(category_id, {}).setdefault(
            seller_id,
            {"count": 0, "popularity": 0},
        )
        bucket["count"] += int(row.get("count") or 0)
        bucket["popularity"] += int(row.get("popularity") or 0)

    stores_by_category: dict[str, list[MarketplaceBusinessPublic]] = {}
    for category_id, sellers in grouped.items():
        ordered = sorted(
            sellers.items(),
            key=lambda item: (
                plan_search_rank(seller_by_id[item[0]]),
                -item[1]["popularity"],
                str(seller_by_id[item[0]].get("store_name") or "").casefold(),
            ),
        )
        stores_by_category[category_id] = [
            _business_to_public(
                seller_by_id[seller_id],
                popularity=stats["popularity"],
                is_local=_seller_is_local_to_municipality(
                    seller_by_id[seller_id],
                    province_id,
                    municipality_id,
                ),
                published_product_count=stats["count"],
                province_id=province_id,
                municipality_id=municipality_id,
            )
            for seller_id, stats in ordered[:FEED_STORES_PER_CATEGORY]
        ]
    return stores_by_category

def _sort_category_ids(stats: dict[str, dict[str, int]]) -> list[str]:
    return sorted(
        stats.keys(),
        key=lambda category_id: (
            -stats[category_id]["popularity"],
            business_category_sort_order(category_id),
        ),
    )

async def list_availability_hints(
    province_id: str,
    municipality_ids: list[str],
    *,
    currency: str | None = None,
    category_id: str | None = None,
) -> MarketplaceAvailabilityHintsPublic:
    """Ejemplos de monedas y categorías con productos cuando la configuración actual no tiene."""
    currencies = _normalize_display_currencies(currency)
    selected_codes = set(currencies or [])
    wants_qusd = "QUSD" in selected_codes
    other_codes = set(_equivalent_currencies([code for code in selected_codes if code != "QUSD"]))
    excluded_hints = set(selected_codes)
    if "USD" in excluded_hints:
        excluded_hints.add("QUSD")
    normalized_category = (
        _normalize_marketplace_category_id(category_id) if category_id and category_id.strip() else None
    )
    seen_municipalities: list[str] = []
    for raw_id in municipality_ids:
        municipality_id = str(raw_id).strip()
        if not municipality_id or municipality_id in seen_municipalities:
            continue
        _validate_location_ids(province_id, municipality_id)
        seen_municipalities.append(municipality_id)
    if not seen_municipalities:
        raise ValueError("Municipio no válido.")

    currency_in_scope: dict[str, int] = {}
    currency_any: dict[str, int] = {}
    category_in_currency: dict[str, int] = {}
    category_any: dict[str, int] = {}
    products_col = get_catalog_products_collection()
    for municipality_id in seen_municipalities:
        seller_by_id, local_ids, delivery_ids, pickup_ids = await _build_marketplace_seller_context(
            province_id,
            municipality_id,
        )
        qvapay_ids = {
            seller_id
            for seller_id, seller in seller_by_id.items()
            if _seller_has_qvapay(seller)
        }
        query = _marketplace_product_query(
            local_ids,
            delivery_ids,
            pickup_seller_ids=pickup_ids or None,
            province_id=province_id,
            municipality_id=municipality_id,
        )
        if query.get("_id") == {"$exists": False}:
            continue
        docs = await products_col.find(
            query,
            {"seller_id": 1, "base_currency": 1, "accepted_currencies": 1, "global_category_id": 1},
        ).to_list(length=400)
        for doc in docs:
            codes = _product_currency_codes(doc)
            category = normalize_business_category_id(str(doc.get("global_category_id") or "otros"))
            category_any[category] = category_any.get(category, 0) + 1
            matches_other = not other_codes or any(code in other_codes for code in codes)
            matches_qusd = wants_qusd and str(doc.get("seller_id") or "") in qvapay_ids
            if not selected_codes:
                matches_currency = True
            elif wants_qusd and not other_codes:
                matches_currency = matches_qusd
            else:
                matches_currency = matches_other or matches_qusd
            in_scope = normalized_category is None or category == normalized_category
            if matches_currency:
                category_in_currency[category] = category_in_currency.get(category, 0) + 1
            for code in codes:
                currency_any[code] = currency_any.get(code, 0) + 1
                if in_scope:
                    currency_in_scope[code] = currency_in_scope.get(code, 0) + 1

    def _top_codes(counts: dict[str, int]) -> list[str]:
        return [
            code
            for code, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            if code not in excluded_hints
        ][:3]

    def _top_categories(counts: dict[str, int]) -> list[str]:
        return [
            item_id
            for item_id, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            if item_id != normalized_category
        ][:3]

    other_currencies = _top_codes(currency_in_scope) or _top_codes(currency_any)
    other_categories = _top_categories(category_in_currency) or _top_categories(category_any)
    return MarketplaceAvailabilityHintsPublic(
        currencies=other_currencies,
        categories=[
            MarketplaceCategoryHint(id=item_id, name=_display_category_name(item_id))
            for item_id in other_categories
        ],
    )

async def list_home_feed(
    province_id: str,
    municipality_id: str,
    *,
    limit_per_category: int = DEFAULT_PAGE_SIZE,
    section_limit: int | None = None,
    section_offset: int = 0,
    municipios_adicionales: list[str] | None = None,
    currency: str | None = None,
) -> MarketplaceHomeFeedPublic:
    currency = _normalize_display_currencies(currency)
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    sales_area_municipality_ids = _selected_sales_area_municipality_ids(
        province_id, municipality_id, municipios_adicionales
    )
    page_size = _normalize_page_size(limit_per_category)
    safe_offset = max(0, section_offset)
    await refresh_popularity_window()
    seller_by_id, local_seller_ids, delivery_seller_ids, pickup_seller_ids = (
        await _build_marketplace_seller_context(
            province_id,
            municipality_id,
            municipios_adicionales=municipios_adicionales,
        )
    )

    if not local_seller_ids and not delivery_seller_ids and not pickup_seller_ids:
        return MarketplaceHomeFeedPublic(
            province_id=province_id,
            province_name=province_name,
            municipality_id=municipality_id,
            municipality_name=municipality_name,
            sections=[],
            total_products=0,
            total_sections=0,
            limit=section_limit or 0,
            offset=safe_offset,
            has_more=False,
        )

    stats_by_category = await _aggregate_category_stats(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids or None,
        currency=currency,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )
    category_ids = [
        category_id
        for category_id in _sort_category_ids(stats_by_category)
        if stats_by_category[category_id]["count"] > 0
    ]
    total_sections = len(category_ids)
    total_products = sum(stats_by_category[category_id]["count"] for category_id in category_ids)
    if section_limit is None:
        reported_limit = total_sections
        page_category_ids = category_ids[safe_offset:]
    else:
        reported_limit = _normalize_page_size(section_limit)
        page_category_ids = category_ids[safe_offset : safe_offset + reported_limit]

    sections: list[MarketplaceCategorySectionPublic] = []
    stores_by_category = await _stores_by_category(
        local_seller_ids,
        delivery_seller_ids,
        page_category_ids,
        seller_by_id,
        pickup_seller_ids=pickup_seller_ids or None,
        currency=currency,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )

    for category_id in page_category_ids:
        total_in_category = stats_by_category[category_id]["count"]

        product_docs = await _list_category_product_docs(
            local_seller_ids,
            delivery_seller_ids,
            category_id,
            pickup_seller_ids=pickup_seller_ids or None,
            currency=currency,
            limit=page_size,
            offset=0,
            province_id=province_id,
            municipality_id=municipality_id,
            sales_area_municipality_ids=sales_area_municipality_ids,
        )
        products = [
            item
            for doc in product_docs
            if (item := _product_to_public(
                doc,
                seller_by_id,
                buyer_province_id=province_id,
                buyer_municipality_id=municipality_id,
                buyer_municipality_ids=sales_area_municipality_ids,
            )) is not None
        ]
        if not products:
            continue

        sections.append(
            MarketplaceCategorySectionPublic(
                category_id=category_id,
                category_name=_display_category_name(category_id),
                products=products,
                stores=stores_by_category.get(category_id, []),
                total_products=total_in_category,
                has_more=total_in_category > len(products),
            )
        )

    return MarketplaceHomeFeedPublic(
        province_id=province_id,
        province_name=province_name,
        municipality_id=municipality_id,
        municipality_name=municipality_name,
        sections=sections,
        total_products=total_products,
        total_sections=total_sections,
        limit=reported_limit,
        offset=safe_offset,
        has_more=safe_offset + len(page_category_ids) < total_sections,
    )

async def list_category_products(
    province_id: str,
    municipality_id: str,
    global_category_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    municipios_adicionales: list[str] | None = None,
    currency: str | None = None,
) -> MarketplaceCategoryProductsPublic:
    currency = _normalize_display_currencies(currency)
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    sales_area_municipality_ids = _selected_sales_area_municipality_ids(
        province_id, municipality_id, municipios_adicionales
    )
    _ = province_name, municipality_name

    normalized_category_id = _normalize_marketplace_category_id(global_category_id)

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)
    await refresh_popularity_window()

    seller_by_id, local_seller_ids, delivery_seller_ids, pickup_seller_ids = (
        await _build_marketplace_seller_context(
            province_id,
            municipality_id,
            municipios_adicionales=municipios_adicionales,
        )
    )

    if not local_seller_ids and not delivery_seller_ids and not pickup_seller_ids:
        return MarketplaceCategoryProductsPublic(
            category_id=normalized_category_id,
            category_name=_display_category_name(normalized_category_id),
            products=[],
            total_products=0,
            limit=page_size,
            offset=safe_offset,
            has_more=False,
        )

    stats_by_category = await _aggregate_category_stats(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids or None,
        currency=currency,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )
    total_in_category = stats_by_category.get(normalized_category_id, {}).get("count", 0)

    product_docs = await _list_category_product_docs(
        local_seller_ids,
        delivery_seller_ids,
        normalized_category_id,
        pickup_seller_ids=pickup_seller_ids or None,
        currency=currency,
        limit=page_size,
        offset=safe_offset,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )
    products = [
        item
        for doc in product_docs
        if (item := _product_to_public(
            doc,
            seller_by_id,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
            buyer_municipality_ids=sales_area_municipality_ids,
        )) is not None    ]

    loaded = safe_offset + len(products)
    return MarketplaceCategoryProductsPublic(
        category_id=normalized_category_id,
        category_name=_display_category_name(normalized_category_id),
        products=products,
        total_products=total_in_category,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_in_category,
    )
