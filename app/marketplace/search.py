"""Búsqueda de productos en la zona y dentro de una tienda."""

from typing import Any
from app.database import get_catalog_products_collection
from app.marketplace.schemas import MarketplaceProductPublic, MarketplaceSearchPublic
from app.products.utils import MARKETPLACE_PRODUCT_SORT, refresh_popularity_window
from app.gestores.service import seller_has_gestores_enabled
from app.marketplace.gestores import (
    _gestor_product_id_filter,
    _public_gestor_margin_map,
    _resolve_public_gestor,
    apply_gestor_to_marketplace_product,
)
from app.marketplace.products import _product_to_public
from app.marketplace.queries import (
    _build_marketplace_products_query,
    _extra_buyer_municipality_ids,
    _seller_store_product_query,
)
from app.marketplace.sellers import _build_marketplace_seller_context, _resolve_store_catalog_seller
from app.marketplace.utils import (
    DEFAULT_PAGE_SIZE,
    _display_category_name,
    _normalize_display_currencies,
    _normalize_marketplace_category_id,
    _normalize_page_size,
    _search_text_filter,
    _selected_sales_area_municipality_ids,
    _validate_location_ids,
)

async def _search_store_catalog(
    province_id: str,
    municipality_id: str,
    *,
    store_slug: str,
    gestor_username: str | None,
    query: str,
    limit: int,
    offset: int,
    currency: str | None,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceSearchPublic:
    extra_municipality_ids = _extra_buyer_municipality_ids(
        province_id,
        municipality_id,
        municipios_adicionales,
    )
    seller = await _resolve_store_catalog_seller(store_slug)
    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    gestor = None
    margins: dict[str, float] = {}
    extra: dict[str, Any] | None = None
    if gestor_username and gestor_username.strip():
        if not seller_has_gestores_enabled(seller):
            raise ValueError("Gestor no encontrado.")
        gestor = await _resolve_public_gestor(seller, gestor_username)
        margins = _public_gestor_margin_map(seller, gestor)
        extra = (
            _gestor_product_id_filter(set(margins.keys()))
            if margins
            else {"_id": {"$exists": False}}
        )

    match_query = _seller_store_product_query(
        seller_id,
        seller,
        province_id,
        municipality_id,
        currency=currency,
        extra=extra,
        municipios_adicionales=municipios_adicionales,
    )
    text_filter = _search_text_filter(query)
    if text_filter and match_query.get("_id") != {"$exists": False}:
        match_query = {"$and": [match_query, text_filter]}

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)
    products_col = get_catalog_products_collection()
    if match_query.get("_id") == {"$exists": False}:
        total_products = 0
        product_docs: list[dict[str, Any]] = []
    else:
        total_products = await products_col.count_documents(match_query)
        product_docs = (
            await products_col.find(match_query)
            .sort(MARKETPLACE_PRODUCT_SORT)
            .skip(safe_offset)
            .limit(page_size)
            .to_list(length=page_size)
        )

    products: list[MarketplaceProductPublic] = []
    for doc in product_docs:
        item = _product_to_public(
            doc,
            seller_by_id,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
            buyer_municipality_ids=extra_municipality_ids,
        )
        if item is None:
            continue
        if gestor is not None:
            margin = margins.get(item.id)
            if margin is None:
                continue
            item = apply_gestor_to_marketplace_product(
                item,
                seller=seller,
                gestor=gestor,
                margin_amount=margin,
            )
        products.append(item)

    loaded = safe_offset + len(products)
    return MarketplaceSearchPublic(
        query=query,
        products=products,
        total_products=total_products,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_products,
    )

async def search_products(
    province_id: str,
    municipality_id: str,
    *,
    query: str = "",
    global_category_id: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    municipios_adicionales: list[str] | None = None,
    currency: str | None = None,
    store_slug: str | None = None,
    gestor_username: str | None = None,
) -> MarketplaceSearchPublic:
    currency = _normalize_display_currencies(currency)
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    sales_area_municipality_ids = _selected_sales_area_municipality_ids(
        province_id, municipality_id, municipios_adicionales
    )
    _ = province_name, municipality_name

    normalized_query = query.strip()
    normalized_category_id = None
    if global_category_id and global_category_id.strip():
        normalized_category_id = _normalize_marketplace_category_id(global_category_id)

    if len(normalized_query) < 2 and not normalized_category_id:
        raise ValueError("Escribe al menos 2 caracteres o elige una categoría.")

    if store_slug and store_slug.strip():
        await refresh_popularity_window()
        return await _search_store_catalog(
            province_id,
            municipality_id,
            store_slug=store_slug.strip(),
            gestor_username=gestor_username,
            query=normalized_query,
            limit=limit,
            offset=offset,
            currency=currency,
            municipios_adicionales=municipios_adicionales,
        )

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

    match_query = await _build_marketplace_products_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids or None,
        global_category_id=normalized_category_id,
        search_text=normalized_query,
        currency=currency,
        province_id=province_id,
        municipality_id=municipality_id,
        sales_area_municipality_ids=sales_area_municipality_ids,
    )

    products_col = get_catalog_products_collection()
    if match_query.get("_id"):
        total_products = 0
        product_docs: list[dict[str, Any]] = []
    else:
        total_products = await products_col.count_documents(match_query)
        product_docs = (
            await products_col.find(match_query)
            .sort(MARKETPLACE_PRODUCT_SORT)
            .skip(safe_offset)
            .limit(page_size)
            .to_list(length=page_size)
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

    return MarketplaceSearchPublic(
        query=normalized_query,
        category_id=normalized_category_id,
        category_name=_display_category_name(normalized_category_id)
        if normalized_category_id
        else None,
        products=products,
        total_products=total_products,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_products,
    )
