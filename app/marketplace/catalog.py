"""Catálogo público de la tienda, sus páginas y su ficha."""

from app.database import get_catalog_products_collection
from app.marketplace.schemas import (
    MarketplaceStoreCatalogPublic,
    MarketplaceStoreCategoryProductsPublic,
    MarketplaceStoreLocalSectionPublic,
    MarketplaceStorePagePublic,
    MarketplaceStorePublic,
)
from app.auth.store_pages import (
    STORE_PAGE_SLUGS,
    STORE_PAGE_TITLES,
    sanitize_store_page_content,
    store_page_flags,
    store_page_has_content,
)
from app.catalogs.catalog_theme import (
    DEFAULT_CATALOG_THEME,
    normalize_catalog_theme,
    public_catalog_palette,
)
from app.products.utils import MARKETPLACE_PRODUCT_SORT, refresh_popularity_window
from app.subscriptions.service import seller_has_full_store_customization
from app.auth.seller_profile import is_profile_complete
from app.subscriptions.service import is_subscription_active
from app.gestores.service import resolve_store_checkout_phones
from app.utils.phone import phone_display
from app.utils.store_slug import store_name_to_slug
from app.marketplace.products import _product_to_public
from app.marketplace.queries import (
    _extra_buyer_municipality_ids,
    _get_local_category_doc,
    _list_store_local_product_docs,
    _seller_store_product_query,
    _store_catalog_category_docs,
)
from app.marketplace.sellers import (
    _find_seller_by_store_ref,
    _resolve_store_catalog_seller,
    _store_profile_fields,
    _store_to_public,
)
from app.marketplace.utils import (
    DEFAULT_PAGE_SIZE,
    _normalize_display_currencies,
    _normalize_page_size,
    _parse_business_area,
    _validate_location_ids,
)

async def get_store_catalog(
    store_ref: str,
    province_id: str,
    municipality_id: str,
    *,
    limit_per_category: int = DEFAULT_PAGE_SIZE,
    currency: str | None = None,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceStoreCatalogPublic:
    currency = _normalize_display_currencies(currency)
    _validate_location_ids(province_id, municipality_id)
    extra_municipality_ids = _extra_buyer_municipality_ids(
        province_id,
        municipality_id,
        municipios_adicionales,
    )
    page_size = _normalize_page_size(limit_per_category)
    await refresh_popularity_window()

    seller = await _resolve_store_catalog_seller(store_ref)
    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    store_public = _store_to_public(seller)
    profile_fields = _store_profile_fields(seller)
    checkout_phones = await resolve_store_checkout_phones(seller)

    products_col = get_catalog_products_collection()

    category_docs = await _store_catalog_category_docs(
        seller_id,
        seller,
        province_id,
        municipality_id,
        currency=currency,
        municipios_adicionales=municipios_adicionales,
    )

    sections: list[MarketplaceStoreLocalSectionPublic] = []
    total_products = 0

    for category_doc in category_docs:
        category_id = str(category_doc["_id"]) if category_doc.get("_id") is not None else "__all__"
        category_oid = category_doc.get("_id")
        category_filter = (
            {}
            if category_oid is None
            else {"category_id": category_oid}
        )
        total_in_category = await products_col.count_documents(
            _seller_store_product_query(
                seller_id,
                seller,
                province_id,
                municipality_id,
                currency=currency,
                extra=category_filter or None,
                municipios_adicionales=municipios_adicionales,
            )
        )
        if total_in_category <= 0:
            continue

        if category_oid is None:
            product_docs = await products_col.find(
                _seller_store_product_query(
                    seller_id,
                    seller,
                    province_id,
                    municipality_id,
                    currency=currency,
                    municipios_adicionales=municipios_adicionales,
                )
            ).sort(MARKETPLACE_PRODUCT_SORT).limit(page_size).to_list(length=page_size)
        else:
            product_docs = await _list_store_local_product_docs(
                seller_id,
                seller,
                province_id,
                municipality_id,
                category_doc,
                limit=page_size,
                offset=0,
                currency=currency,
                municipios_adicionales=municipios_adicionales,
            )
        products = [
            item
            for doc in product_docs
            if (item := _product_to_public(
                doc,
                seller_by_id,
                buyer_province_id=province_id,
                buyer_municipality_id=municipality_id,
                buyer_municipality_ids=extra_municipality_ids,
            )) is not None
        ]
        if not products:
            continue

        sections.append(
            MarketplaceStoreLocalSectionPublic(
                category_id=category_id,
                category_name=category_doc["name"],
                products=products,
                total_products=total_in_category,
                has_more=total_in_category > len(products),
            )
        )
        total_products += total_in_category

    return MarketplaceStoreCatalogPublic(
        store=store_public,
        sections=sections,
        total_products=total_products,
        checkout_phones=checkout_phones,
        **profile_fields,
    )

async def list_store_category_products(
    store_ref: str,
    province_id: str,
    municipality_id: str,
    local_category_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    currency: str | None = None,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceStoreCategoryProductsPublic:
    currency = _normalize_display_currencies(currency)
    _validate_location_ids(province_id, municipality_id)
    extra_municipality_ids = _extra_buyer_municipality_ids(
        province_id,
        municipality_id,
        municipios_adicionales,
    )

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)
    await refresh_popularity_window()

    seller = await _resolve_store_catalog_seller(store_ref)
    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    category_doc = await _get_local_category_doc(seller_id, local_category_id)
    category_oid = category_doc["_id"]

    products_col = get_catalog_products_collection()
    total_in_category = await products_col.count_documents(
        _seller_store_product_query(
            seller_id,
            seller,
            province_id,
            municipality_id,
            currency=currency,
            extra={"category_id": category_oid},
            municipios_adicionales=municipios_adicionales,
        )
    )

    product_docs = await _list_store_local_product_docs(
        seller_id,
        seller,
        province_id,
        municipality_id,
        category_doc,
        limit=page_size,
        offset=safe_offset,
        currency=currency,
        municipios_adicionales=municipios_adicionales,
    )
    products = [
        item
        for doc in product_docs
        if (item := _product_to_public(
            doc,
            seller_by_id,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
            buyer_municipality_ids=extra_municipality_ids,
        )) is not None    ]

    loaded = safe_offset + len(products)
    return MarketplaceStoreCategoryProductsPublic(
        category_id=str(category_oid),
        category_name=category_doc["name"],
        products=products,
        total_products=total_in_category,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_in_category,
    )

async def get_store_page(store_ref: str, page_slug: str) -> MarketplaceStorePagePublic:
    from fastapi import HTTPException

    key = STORE_PAGE_SLUGS.get((page_slug or "").strip().lower())
    if not key:
        raise ValueError("Página no encontrada.")

    seller = await _find_seller_by_store_ref(store_ref)
    if not is_subscription_active(seller) or not is_profile_complete(seller):
        raise ValueError("Página no encontrada.")

    raw_pages = seller.get("store_pages")
    raw = raw_pages.get(key) if isinstance(raw_pages, dict) else None
    if not store_page_has_content(raw):
        raise ValueError("Página no encontrada.")
    try:
        content = sanitize_store_page_content(raw)
    except HTTPException as exc:
        raise ValueError("Página no encontrada.") from exc

    customized = seller_has_full_store_customization(seller)
    area = _parse_business_area(seller.get("business_area"))
    phone_digits = seller.get("phone")
    return MarketplaceStorePagePublic(
        store_name=seller["store_name"],
        store_slug=seller.get("store_slug") or store_name_to_slug(seller["store_name"]),
        page=key,
        title=STORE_PAGE_TITLES[key],
        content=content,
        catalog_theme=(
            normalize_catalog_theme(seller.get("catalog_theme"))
            if customized
            else DEFAULT_CATALOG_THEME
        ),
        catalog_palette=(
            public_catalog_palette(seller.get("catalog_palette"), seller.get("catalog_theme"))
            if customized
            else None
        ),
        store_pages=store_page_flags(seller),
        profile_photo_url=seller.get("profile_photo_url"),
        province_name=area.province_name if area else None,
        phone=phone_display(phone_digits) if phone_digits else None,
        offers_delivery=bool(seller.get("offers_delivery")),
    )

async def get_store_public(store_ref: str) -> MarketplaceStorePublic:
    seller = await _find_seller_by_store_ref(store_ref)

    if not is_subscription_active(seller):
        raise ValueError("Tienda no encontrada.")

    if not is_profile_complete(seller):
        raise ValueError("Esta tienda aún no ha completado su perfil público.")

    phone_digits = seller.get("phone")
    if not phone_digits:
        raise ValueError("La tienda no tiene teléfono registrado.")

    store = _store_to_public(seller)
    checkout_phones = await resolve_store_checkout_phones(seller)
    return store.model_copy(update={"checkout_phones": checkout_phones})
