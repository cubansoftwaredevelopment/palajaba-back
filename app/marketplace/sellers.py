"""Tiendas visibles, localidad y datos públicos del vendedor."""

import re
from typing import Any
from bson import ObjectId
from bson.errors import InvalidId
from app.database import get_registrations_collection, get_seller_profile_views_collection
from app.marketplace.schemas import MarketplaceStorePublic
from app.categories.schemas import CategoryPublic
from app.auth.seller_profile import store_banners_from_document
from app.auth.store_pages import store_page_flags
from app.categories.service import (
    business_category_name,
    business_category_source_ids,
    normalize_business_category_id,
)
from app.catalogs.catalog_theme import (
    DEFAULT_CATALOG_THEME,
    normalize_catalog_theme,
    public_catalog_palette,
)
from app.subscriptions.service import seller_has_full_store_customization, seller_has_store_banners
from app.auth.seller_profile import is_profile_complete, social_links_from_document
from app.subscriptions.service import is_subscription_active
from app.utils.phone import phone_display
from app.utils.store_slug import decode_store_ref, store_name_to_slug
from app.marketplace.utils import (
    _normalize_additional_municipalities,
    _parse_business_area,
    _parse_business_location,
    _parse_delivery_areas,
)

def _store_profile_fields(seller: dict[str, Any]) -> dict[str, Any]:
    category_ids = list(seller.get("category_ids") or [])
    return {
        "biography": seller.get("biography"),
        "social_instagram": seller.get("social_instagram"),
        "social_facebook": seller.get("social_facebook"),
        "social_links": social_links_from_document(seller),
        "business_location": _parse_business_location(seller.get("business_location")),
        "business_area": _parse_business_area(seller.get("business_area")),
        "delivery_areas": _parse_delivery_areas(seller.get("delivery_areas")),
        "categories": [
            CategoryPublic(id=category_id, name=business_category_name(category_id))
            for category_id in category_ids
        ],
        "offers_delivery": seller.get("offers_delivery"),
        "catalog_theme": (
            normalize_catalog_theme(seller.get("catalog_theme"))
            if seller_has_full_store_customization(seller)
            else DEFAULT_CATALOG_THEME
        ),
        "catalog_palette": (
            public_catalog_palette(seller.get("catalog_palette"), seller.get("catalog_theme"))
            if seller_has_full_store_customization(seller)
            else None
        ),
        "banners": (
            store_banners_from_document(seller, active_only=True)
            if seller_has_store_banners(seller)
            else []
        ),
        "store_pages": store_page_flags(seller),
    }

_service_fee_percent = 0.0

def set_marketplace_service_fee_percent(percent: float) -> None:
    global _service_fee_percent
    try:
        value = float(percent or 0)
    except (TypeError, ValueError):
        value = 0.0
    _service_fee_percent = min(100.0, max(0.0, value))

def _service_fee_for_seller(seller: dict[str, Any]) -> float:
    from app.payments.qvapay import qvapay_escrow_configured

    if _service_fee_percent <= 0:
        return 0.0
    if not seller.get("qvapay_username") or not qvapay_escrow_configured():
        return 0.0
    return _service_fee_percent

def _store_to_public(seller: dict[str, Any]) -> MarketplaceStorePublic:
    from app.payments.qvapay import qvapay_escrow_configured
    from app.subscriptions.plugins import seller_has_plugin

    seller_id = str(seller["_id"])
    return MarketplaceStorePublic(
        id=seller_id,
        store_name=seller["store_name"],
        store_slug=seller.get("store_slug") or store_name_to_slug(seller["store_name"]),
        phone=phone_display(seller["phone"]),
        qvapay_enabled=bool(seller.get("qvapay_username")) and qvapay_escrow_configured(),
        whatsapp_orders_enabled=seller_has_plugin(seller, "whatsapp_orders"),
        profile_photo_url=seller.get("profile_photo_url"),
        business_area=_parse_business_area(seller.get("business_area")),
        store_pages=store_page_flags(seller),
    )

async def _find_seller_by_store_ref(store_ref: str) -> dict[str, Any]:
    decoded = decode_store_ref(store_ref)
    if not decoded:
        raise ValueError("Tienda no válida.")

    collection = get_registrations_collection()

    if len(decoded) == 24:
        try:
            seller = await collection.find_one({"_id": ObjectId(decoded), "deleted_at": None})
            if seller is not None:
                return seller
        except InvalidId:
            pass

    slug = store_name_to_slug(decoded)
    if slug:
        seller = await collection.find_one({"store_slug": slug, "deleted_at": None})
        if seller is not None:
            return seller

    seller = await collection.find_one(
        {
            "store_name": {"$regex": f"^{re.escape(decoded)}$", "$options": "i"},
            "deleted_at": None,
        }
    )
    if seller is not None:
        return seller

    raise ValueError("Tienda no encontrada.")

async def _resolve_visible_seller(
    store_ref: str,
    province_id: str,
    municipality_id: str,
) -> dict[str, Any]:
    seller_doc = await _find_seller_by_store_ref(store_ref)
    seller_by_id = await _get_visible_sellers(province_id, municipality_id)
    seller_id = str(seller_doc["_id"])
    seller = seller_by_id.get(seller_id)
    if seller is None:
        raise ValueError("Tienda no encontrada o no disponible en tu zona.")
    return seller

async def _resolve_store_catalog_seller(store_ref: str) -> dict[str, Any]:
    """Página pública de una tienda: no exige que el comprador esté en la misma zona."""
    seller = await _find_seller_by_store_ref(store_ref)

    if not is_subscription_active(seller):
        raise ValueError("Tienda no encontrada.")

    if not is_profile_complete(seller):
        raise ValueError("Esta tienda aún no ha completado su perfil público.")

    return seller

async def resolve_visible_seller_id(
    store_ref: str,
    province_id: str,
    municipality_id: str,
) -> str:
    seller = await _resolve_visible_seller(store_ref, province_id, municipality_id)
    return str(seller["_id"])

async def _get_visible_sellers(
    province_id: str,
    municipality_id: str,
) -> dict[str, dict[str, Any]]:
    registrations = get_registrations_collection()
    seller_query = {
        "status": "approved",
        "deleted_at": None,
        "profile_photo_url": {"$exists": True, "$ne": None},
        "offers_delivery": {"$exists": True},
        "business_area": {"$exists": True},
        "$or": [
            {
                "business_area.province_id": province_id,
                "business_area.municipality_id": municipality_id,
            },
            {
                "delivery_areas": {
                    "$elemMatch": {
                        "province_id": province_id,
                        "municipality_id": municipality_id,
                    }
                }
            },
        ],
    }

    seller_docs = await registrations.find(seller_query).to_list(length=None)
    visible_sellers = [
        doc
        for doc in seller_docs
        if is_subscription_active(doc) and is_profile_complete(doc)
    ]
    return {str(doc["_id"]): doc for doc in visible_sellers}

async def _get_pickup_sellers_in_municipalities(
    province_id: str,
    municipality_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not municipality_ids:
        return {}

    registrations = get_registrations_collection()
    seller_query = {
        "status": "approved",
        "deleted_at": None,
        "profile_photo_url": {"$exists": True, "$ne": None},
        "offers_delivery": {"$exists": True},
        "business_area": {"$exists": True},
        "$or": [
            {
                "business_area.province_id": province_id,
                "business_area.municipality_id": municipality_id,
            }
            for municipality_id in municipality_ids
        ],
    }

    seller_docs = await registrations.find(seller_query).to_list(length=None)
    visible_sellers = [
        doc
        for doc in seller_docs
        if is_subscription_active(doc) and is_profile_complete(doc)
    ]
    return {str(doc["_id"]): doc for doc in visible_sellers}

async def _build_marketplace_seller_context(
    province_id: str,
    municipality_id: str,
    *,
    municipios_adicionales: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str], list[str], list[str]]:
    additional_municipality_ids = _normalize_additional_municipalities(
        province_id,
        municipality_id,
        municipios_adicionales,
    )

    seller_by_id = await _get_visible_sellers(province_id, municipality_id)
    local_seller_ids, delivery_seller_ids = _split_sellers_by_locality(
        seller_by_id,
        province_id,
        municipality_id,
    )

    pickup_seller_by_id = await _get_pickup_sellers_in_municipalities(
        province_id,
        additional_municipality_ids,
    )
    pickup_seller_ids = list(pickup_seller_by_id.keys())
    merged_seller_by_id = {**seller_by_id, **pickup_seller_by_id}

    return merged_seller_by_id, local_seller_ids, delivery_seller_ids, pickup_seller_ids

def _seller_is_local_to_municipality(
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
) -> bool:
    area = seller.get("business_area")
    if not isinstance(area, dict):
        return False
    return (
        area.get("province_id") == province_id
        and area.get("municipality_id") == municipality_id
    )

def _seller_delivers_to_municipality(
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
) -> bool:
    if not seller.get("offers_delivery"):
        return False
    for area in _parse_delivery_areas(seller.get("delivery_areas")):
        if area.province_id == province_id and area.municipality_id == municipality_id:
            return True
    return False

def _product_pickup_info(
    product: dict[str, Any],
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
) -> tuple[bool, str | None]:
    if _seller_is_local_to_municipality(seller, province_id, municipality_id):
        return False, None
    if product.get("offers_delivery") and _seller_delivers_to_municipality(
        seller,
        province_id,
        municipality_id,
    ):
        return False, None

    area = seller.get("business_area")
    municipality_name = area.get("municipality_name") if isinstance(area, dict) else None
    return True, municipality_name

def _split_sellers_by_locality(
    seller_by_id: dict[str, dict[str, Any]],
    province_id: str,
    municipality_id: str,
) -> tuple[list[str], list[str]]:
    local_ids: list[str] = []
    delivery_ids: list[str] = []
    for seller_id, seller in seller_by_id.items():
        if _seller_is_local_to_municipality(seller, province_id, municipality_id):
            local_ids.append(seller_id)
        else:
            delivery_ids.append(seller_id)
    return local_ids, delivery_ids

def _seller_has_qvapay(seller: dict[str, Any]) -> bool:
    return bool(str(seller.get("qvapay_username") or "").strip())

async def _qvapay_seller_ids(seller_ids: list[str]) -> list[str]:
    object_ids: list[ObjectId] = []
    for seller_id in seller_ids:
        try:
            object_ids.append(ObjectId(seller_id))
        except InvalidId:
            continue
    if not object_ids:
        return []
    docs = await get_registrations_collection().find(
        {"_id": {"$in": object_ids}},
        {"qvapay_username": 1},
    ).to_list(length=None)
    return [str(doc["_id"]) for doc in docs if _seller_has_qvapay(doc)]

def _business_pickup_info(
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
) -> tuple[bool, str | None, str | None]:
    pickup_required, municipality_name = _product_pickup_info(
        {"offers_delivery": seller.get("offers_delivery")},
        seller,
        province_id,
        municipality_id,
    )
    pickup_notice = None
    if pickup_required:
        if municipality_name:
            pickup_notice = (
                f"Sin domicilio a tu municipio · Recoger en {municipality_name}"
            )
        else:
            pickup_notice = "Sin domicilio a tu municipio"
    return pickup_required, municipality_name, pickup_notice

def _seller_matches_business_search(seller: dict[str, Any], query_text: str) -> bool:
    normalized = query_text.strip()
    if not normalized:
        return True
    pattern = normalized.casefold()
    store_name = (seller.get("store_name") or "").casefold()
    biography = (seller.get("biography") or "").casefold()
    return pattern in store_name or pattern in biography

def _seller_matches_business_category(
    seller: dict[str, Any],
    category_id: str | None,
) -> bool:
    if not category_id:
        return True
    canonical_id = normalize_business_category_id(category_id)
    source_ids = set(business_category_source_ids(canonical_id))
    for raw_id in seller.get("category_ids") or []:
        if normalize_business_category_id(str(raw_id)) == canonical_id:
            return True
        if str(raw_id) in source_ids:
            return True
    return False

async def _aggregate_seller_popularity(seller_ids: list[str]) -> dict[str, int]:
    if not seller_ids:
        return {}

    views_col = get_seller_profile_views_collection()
    pipeline = [
        {"$match": {"seller_id": {"$in": seller_ids}}},
        {"$group": {"_id": "$seller_id", "popularity": {"$sum": 1}}},
    ]
    rows = await views_col.aggregate(pipeline).to_list(length=None)
    return {str(row["_id"]): int(row.get("popularity") or 0) for row in rows}
