"""Catálogo público atribuido a un gestor."""

from typing import Any
from bson import ObjectId
from bson.errors import InvalidId
from app.database import get_catalog_products_collection, get_gestores_collection
from app.marketplace.schemas import (
    MarketplaceGestorProductPublic,
    MarketplaceGestorPublic,
    MarketplaceGestorStoreCatalogPublic,
    MarketplaceGestorStoreCategoryProductsPublic,
    MarketplaceGestorStoreLocalSectionPublic,
    MarketplaceProductPublic,
)
from app.products.utils import MARKETPLACE_PRODUCT_SORT, refresh_popularity_window
from app.gestores.service import (
    compute_gestor_display_price,
    parse_gestor_catalog_access,
    parse_selected_products,
    product_is_allowed_for_gestores,
    seller_has_gestores_enabled,
    validate_gestor_username,
)
from app.utils.phone import phone_display
from app.marketplace.products import _product_to_public
from app.marketplace.queries import (
    _extra_buyer_municipality_ids,
    _get_local_category_doc,
    _list_store_local_product_docs,
    _seller_store_product_query,
    _store_catalog_category_docs,
)
from app.marketplace.sellers import (
    _resolve_store_catalog_seller,
    _store_profile_fields,
    _store_to_public,
)
from app.marketplace.utils import (
    DEFAULT_PAGE_SIZE,
    _normalize_display_currencies,
    _normalize_page_size,
    _validate_location_ids,
)

def _gestor_product_id_filter(product_ids: set[str]) -> dict[str, Any]:
    oids: list[ObjectId] = []
    for product_id in product_ids:
        try:
            oids.append(ObjectId(product_id))
        except InvalidId:
            continue
    return {"_id": {"$in": oids}}

def _gestor_public_ref(gestor: dict[str, Any]) -> MarketplaceGestorPublic:
    phone_digits = str(gestor.get("phone") or "").strip()
    return MarketplaceGestorPublic(
        id=str(gestor["_id"]),
        username=str(gestor["username"]),
        phone=phone_display(phone_digits) if phone_digits else "",
    )

def _public_gestor_margin_map(
    seller: dict[str, Any],
    gestor: dict[str, Any],
) -> dict[str, float]:
    access = parse_gestor_catalog_access(seller.get("gestor_catalog_access"))
    margins: dict[str, float] = {}
    for item in parse_selected_products(gestor.get("selected_products")):
        if not product_is_allowed_for_gestores(access, item.product_id):
            continue
        margins[item.product_id] = float(item.margin_amount)
    return margins

async def _resolve_public_gestor(seller: dict[str, Any], username: str) -> dict[str, Any]:
    try:
        normalized = validate_gestor_username(username)
    except ValueError as exc:
        raise ValueError("Gestor no encontrado.") from exc

    gestor = await get_gestores_collection().find_one(
        {"seller_id": seller["_id"], "username": normalized}
    )
    if (
        gestor is None
        or gestor.get("is_active", True) is False
        or not gestor.get("password_hash")
        or not gestor.get("phone")
    ):
        raise ValueError("Gestor no encontrado.")
    return gestor

def apply_gestor_to_marketplace_product(
    product: MarketplaceProductPublic,
    *,
    seller: dict[str, Any],
    gestor: dict[str, Any],
    margin_amount: float,
) -> MarketplaceGestorProductPublic:
    """Precio público = base + margen; WhatsApp usa el teléfono del gestor."""
    store = _store_to_public(seller).model_copy(
        update={"phone": _gestor_public_ref(gestor).phone}
    )
    base = product.model_dump()
    base.update(
        {
            "base_price": compute_gestor_display_price(product.base_price, margin_amount),
            "store": store,
            "gestor_id": str(gestor["_id"]),
            "gestor_username": str(gestor["username"]),
        }
    )
    return MarketplaceGestorProductPublic(**base)

async def get_gestor_store_catalog(
    store_ref: str,
    gestor_username: str,
    province_id: str,
    municipality_id: str,
    *,
    limit_per_category: int = DEFAULT_PAGE_SIZE,
    currency: str | None = None,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceGestorStoreCatalogPublic:
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
    if not seller_has_gestores_enabled(seller):
        raise ValueError("Gestor no encontrado.")
    gestor = await _resolve_public_gestor(seller, gestor_username)
    margins = _public_gestor_margin_map(seller, gestor)
    gestor_public = _gestor_public_ref(gestor)

    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    store_public = _store_to_public(seller)
    profile_fields = _store_profile_fields(seller)

    if not margins:
        return MarketplaceGestorStoreCatalogPublic(
            store=store_public,
            sections=[],
            total_products=0,
            gestor=gestor_public,
            **profile_fields,
        )

    id_filter = _gestor_product_id_filter(set(margins.keys()))
    products_col = get_catalog_products_collection()
    category_docs = await _store_catalog_category_docs(
        seller_id,
        seller,
        province_id,
        municipality_id,
        currency=currency,
        municipios_adicionales=municipios_adicionales,
    )

    sections: list[MarketplaceGestorStoreLocalSectionPublic] = []
    total_products = 0

    for category_doc in category_docs:
        category_id = str(category_doc["_id"]) if category_doc.get("_id") is not None else "__all__"
        category_oid = category_doc.get("_id")
        category_filter = (
            {**id_filter}
            if category_oid is None
            else {**id_filter, "category_id": category_oid}
        )
        total_in_category = await products_col.count_documents(
            _seller_store_product_query(
                seller_id,
                seller,
                province_id,
                municipality_id,
                currency=currency,
                extra=category_filter,
                municipios_adicionales=municipios_adicionales,
            )
        )
        if total_in_category <= 0:
            continue

        if category_oid is None:
            product_docs = (
                await products_col.find(
                    _seller_store_product_query(
                        seller_id,
                        seller,
                        province_id,
                        municipality_id,
                        currency=currency,
                        extra=id_filter,
                        municipios_adicionales=municipios_adicionales,
                    )
                )
                .sort(MARKETPLACE_PRODUCT_SORT)
                .limit(page_size)
                .to_list(length=page_size)
            )
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
                extra=id_filter,
                municipios_adicionales=municipios_adicionales,
            )

        products: list[MarketplaceGestorProductPublic] = []
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
            margin = margins.get(item.id)
            if margin is None:
                continue
            products.append(
                apply_gestor_to_marketplace_product(
                    item,
                    seller=seller,
                    gestor=gestor,
                    margin_amount=margin,
                )
            )
        if not products:
            continue

        sections.append(
            MarketplaceGestorStoreLocalSectionPublic(
                category_id=category_id,
                category_name=category_doc["name"],
                products=products,
                total_products=total_in_category,
                has_more=total_in_category > len(products),
            )
        )
        total_products += total_in_category

    return MarketplaceGestorStoreCatalogPublic(
        store=store_public,
        sections=sections,
        total_products=total_products,
        gestor=gestor_public,
        **profile_fields,
    )

async def list_gestor_store_category_products(
    store_ref: str,
    gestor_username: str,
    province_id: str,
    municipality_id: str,
    local_category_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    currency: str | None = None,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceGestorStoreCategoryProductsPublic:
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
    if not seller_has_gestores_enabled(seller):
        raise ValueError("Gestor no encontrado.")
    gestor = await _resolve_public_gestor(seller, gestor_username)
    margins = _public_gestor_margin_map(seller, gestor)
    gestor_public = _gestor_public_ref(gestor)

    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    category_doc = await _get_local_category_doc(seller_id, local_category_id)
    category_oid = category_doc["_id"]

    if not margins:
        return MarketplaceGestorStoreCategoryProductsPublic(
            category_id=str(category_oid),
            category_name=category_doc["name"],
            products=[],
            total_products=0,
            limit=page_size,
            offset=safe_offset,
            has_more=False,
            gestor=gestor_public,
        )

    id_filter = _gestor_product_id_filter(set(margins.keys()))
    products_col = get_catalog_products_collection()
    total_in_category = await products_col.count_documents(
        _seller_store_product_query(
            seller_id,
            seller,
            province_id,
            municipality_id,
            currency=currency,
            extra={**id_filter, "category_id": category_oid},
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
        extra=id_filter,
        municipios_adicionales=municipios_adicionales,
    )

    products: list[MarketplaceGestorProductPublic] = []
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
        margin = margins.get(item.id)
        if margin is None:
            continue
        products.append(
            apply_gestor_to_marketplace_product(
                item,
                seller=seller,
                gestor=gestor,
                margin_amount=margin,
            )
        )

    loaded = safe_offset + len(products)
    return MarketplaceGestorStoreCategoryProductsPublic(
        category_id=str(category_oid),
        category_name=category_doc["name"],
        products=products,
        total_products=total_in_category,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_in_category,
        gestor=gestor_public,
    )
