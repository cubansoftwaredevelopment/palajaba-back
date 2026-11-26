"""Listado de tiendas que venden en la zona."""

from typing import Any
from app.marketplace.schemas import MarketplaceBusinessPublic, MarketplaceBusinessesPublic
from app.categories.schemas import CategoryPublic
from app.auth.registration_insights import aggregate_product_counts_by_seller
from app.categories.service import business_category_name, normalize_business_category_id
from app.subscriptions.service import plan_search_rank
from app.marketplace.queries import _seller_acceptance_counts
from app.marketplace.sellers import (
    _aggregate_seller_popularity,
    _build_marketplace_seller_context,
    _business_pickup_info,
    _seller_is_local_to_municipality,
    _seller_matches_business_category,
    _seller_matches_business_search,
    _store_to_public,
)
from app.marketplace.utils import (
    DEFAULT_PAGE_SIZE,
    _display_category_name,
    _listable_product_count,
    _normalize_display_currencies,
    _normalize_page_size,
    _parse_business_area,
    _validate_location_ids,
)

def _business_to_public(
    seller: dict[str, Any],
    *,
    popularity: int,
    is_local: bool,
    published_product_count: int = 0,
    province_id: str,
    municipality_id: str,
) -> MarketplaceBusinessPublic:
    category_ids = list(seller.get("category_ids") or [])
    pickup_required, pickup_municipality_name, pickup_notice = _business_pickup_info(
        seller,
        province_id,
        municipality_id,
    )
    return MarketplaceBusinessPublic(
        store=_store_to_public(seller),
        business_area=_parse_business_area(seller.get("business_area")),
        offers_delivery=seller.get("offers_delivery"),
        categories=[
            CategoryPublic(id=category_id, name=business_category_name(category_id))
            for category_id in category_ids
        ],
        popularity=popularity,
        is_local=is_local,
        published_product_count=published_product_count,
        pickup_required=pickup_required,
        pickup_municipality_name=pickup_municipality_name,
        pickup_notice=pickup_notice,
    )

async def list_businesses(
    province_id: str,
    municipality_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    query: str = "",
    category_id: str | None = None,
    municipios_adicionales: list[str] | None = None,
    currency: str | None = None,
) -> MarketplaceBusinessesPublic:
    currency = _normalize_display_currencies(currency)
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)

    normalized_query = query.strip()
    normalized_category_id = None
    if category_id and category_id.strip():
        normalized_category_id = normalize_business_category_id(category_id.strip())

    if normalized_query and len(normalized_query) < 2 and not normalized_category_id:
        raise ValueError("Escribe al menos 2 caracteres o elige una categoría.")

    seller_by_id, _, _, _ = await _build_marketplace_seller_context(
        province_id,
        municipality_id,
        municipios_adicionales=municipios_adicionales,
    )
    if not seller_by_id:
        return MarketplaceBusinessesPublic(
            province_id=province_id,
            province_name=province_name,
            municipality_id=municipality_id,
            municipality_name=municipality_name,
            query=normalized_query,
            category_id=normalized_category_id,
            category_name=_display_category_name(normalized_category_id)
            if normalized_category_id
            else None,
            businesses=[],
            total_businesses=0,
            limit=page_size,
            offset=safe_offset,
            has_more=False,
        )

    popularity_by_seller = await _aggregate_seller_popularity(list(seller_by_id.keys()))
    product_counts_by_seller = await aggregate_product_counts_by_seller(list(seller_by_id.keys()))
    acceptance_counts = await _seller_acceptance_counts(list(seller_by_id.keys()), currency)
    ranked: list[tuple[int, int, str, dict[str, Any], bool, int]] = []
    for seller_id, seller in seller_by_id.items():
        if not _seller_matches_business_search(seller, normalized_query):
            continue
        if not _seller_matches_business_category(seller, normalized_category_id):
            continue

        if acceptance_counts is None:
            listable_count = _listable_product_count(product_counts_by_seller.get(seller_id))
        else:
            listable_count = acceptance_counts.get(seller_id, 0)
        if listable_count < 1:
            continue

        is_local = _seller_is_local_to_municipality(seller, province_id, municipality_id)
        popularity = popularity_by_seller.get(seller_id, 0)
        ranked.append(
            (
                plan_search_rank(seller),
                -popularity,
                seller.get("store_name", "").casefold(),
                seller,
                is_local,
                listable_count,
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    total_businesses = len(ranked)
    page_rows = ranked[safe_offset : safe_offset + page_size]
    businesses = [
        _business_to_public(
            seller,
            popularity=-popularity,
            is_local=is_local,
            published_product_count=accepted_count,
            province_id=province_id,
            municipality_id=municipality_id,
        )
        for _rank, popularity, _, seller, is_local, accepted_count in page_rows
    ]

    loaded = safe_offset + len(businesses)
    return MarketplaceBusinessesPublic(
        province_id=province_id,
        province_name=province_name,
        municipality_id=municipality_id,
        municipality_name=municipality_name,
        query=normalized_query,
        category_id=normalized_category_id,
        category_name=_display_category_name(normalized_category_id)
        if normalized_category_id
        else None,
        businesses=businesses,
        total_businesses=total_businesses,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_businesses,
    )
