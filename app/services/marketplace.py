import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.schemas.marketplace import (
    JabaRemovedProductPublic,
    JabaSyncPublic,
    JabaSyncRequest,
    MarketplaceCategoryProductsPublic,
    MarketplaceCategorySectionPublic,
    MarketplaceHomeFeedPublic,
    MarketplaceProductPublic,
    MarketplaceSearchPublic,
    MarketplaceStoreCatalogPublic,
    MarketplaceStoreCategoryProductsPublic,
    MarketplaceStoreLocalSectionPublic,
    MarketplaceStorePublic,
)
from app.schemas.seller_profile import BusinessArea, BusinessLocation, CategoryPublic
from app.services.cuba_locations import MUNICIPALITIES_BY_PROVINCE, PROVINCE_NAMES
from app.services.categories import (
    DEFAULT_CATEGORIES,
    business_category_name,
    business_category_sort_order,
)
from app.services.product_categories import (
    REVOLICO_PRODUCT_CATEGORIES,
    category_name as product_category_name,
    category_sort_order,
)
from app.services.product_popularity import MARKETPLACE_PRODUCT_SORT
from app.services.seller_profile import is_profile_complete
from app.services.subscriptions import is_subscription_active
from app.utils.phone import phone_display
from app.utils.store_slug import decode_store_ref, store_name_to_slug

KNOWN_BUSINESS_CATEGORY_IDS = {item["id"] for item in DEFAULT_CATEGORIES}
KNOWN_PRODUCT_CATEGORY_IDS = {item["id"] for item in REVOLICO_PRODUCT_CATEGORIES}


def _display_category_name(category_id: str) -> str:
    name = business_category_name(category_id)
    if name != "Otros":
        return name
    return product_category_name(category_id)


def _normalize_marketplace_category_id(category_id: str) -> str:
    normalized = category_id.strip().lower()
    if normalized in KNOWN_BUSINESS_CATEGORY_IDS or normalized in KNOWN_PRODUCT_CATEGORY_IDS:
        return normalized
    raise ValueError("Categoría no válida.")


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def _validate_location_ids(province_id: str, municipality_id: str) -> tuple[str, str]:
    province_name = PROVINCE_NAMES.get(province_id)
    if not province_name:
        raise ValueError("Provincia no válida.")

    municipalities = MUNICIPALITIES_BY_PROVINCE.get(province_id, {})
    municipality_name = municipalities.get(municipality_id)
    if not municipality_name:
        raise ValueError("Municipio no válido para la provincia seleccionada.")

    return province_name, municipality_name


def _normalize_additional_municipalities(
    province_id: str,
    base_municipality_id: str,
    municipios_adicionales: list[str] | None,
) -> list[str]:
    if not municipios_adicionales:
        return []

    municipalities = MUNICIPALITIES_BY_PROVINCE.get(province_id, {})
    if not municipalities:
        raise ValueError("Provincia no válida.")

    normalized_base = base_municipality_id.strip()
    seen: set[str] = set()
    result: list[str] = []

    for raw_id in municipios_adicionales:
        municipality_id = raw_id.strip()
        if not municipality_id or municipality_id == normalized_base:
            continue
        if municipality_id not in municipalities:
            raise ValueError(
                f"Municipio adicional no válido para la provincia: {municipality_id}."
            )
        if municipality_id not in seen:
            seen.add(municipality_id)
            result.append(municipality_id)

    return result


def _normalize_page_size(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))


def _parse_business_area(raw: Any) -> BusinessArea | None:
    if not isinstance(raw, dict):
        return None
    required = ("province_id", "province_name", "municipality_id", "municipality_name")
    if not all(raw.get(key) for key in required):
        return None
    return BusinessArea(
        province_id=raw["province_id"],
        province_name=raw["province_name"],
        municipality_id=raw["municipality_id"],
        municipality_name=raw["municipality_name"],
    )


def _parse_delivery_areas(raw: Any) -> list[BusinessArea]:
    if not isinstance(raw, list):
        return []
    areas: list[BusinessArea] = []
    for item in raw:
        parsed = _parse_business_area(item)
        if parsed is not None:
            areas.append(parsed)
    return areas


def _parse_business_location(raw: Any) -> BusinessLocation | None:
    if not isinstance(raw, dict) or raw.get("lat") is None:
        return None
    return BusinessLocation(
        lat=raw["lat"],
        lng=raw["lng"],
        label=raw.get("label"),
    )


def _store_profile_fields(seller: dict[str, Any]) -> dict[str, Any]:
    category_ids = list(seller.get("category_ids") or [])
    return {
        "biography": seller.get("biography"),
        "social_instagram": seller.get("social_instagram"),
        "social_facebook": seller.get("social_facebook"),
        "business_location": _parse_business_location(seller.get("business_location")),
        "business_area": _parse_business_area(seller.get("business_area")),
        "delivery_areas": _parse_delivery_areas(seller.get("delivery_areas")),
        "categories": [
            CategoryPublic(id=category_id, name=business_category_name(category_id))
            for category_id in category_ids
        ],
        "offers_delivery": seller.get("offers_delivery"),
    }


def _store_to_public(seller: dict[str, Any]) -> MarketplaceStorePublic:
    seller_id = str(seller["_id"])
    return MarketplaceStorePublic(
        id=seller_id,
        store_name=seller["store_name"],
        store_slug=seller.get("store_slug") or store_name_to_slug(seller["store_name"]),
        phone=phone_display(seller["phone"]),
        profile_photo_url=seller.get("profile_photo_url"),
    )


async def _find_seller_by_store_ref(store_ref: str) -> dict[str, Any]:
    decoded = decode_store_ref(store_ref)
    if not decoded:
        raise ValueError("Tienda no válida.")

    collection = get_registrations_collection()

    if len(decoded) == 24:
        try:
            seller = await collection.find_one({"_id": ObjectId(decoded)})
            if seller is not None:
                return seller
        except InvalidId:
            pass

    slug = store_name_to_slug(decoded)
    if slug:
        seller = await collection.find_one({"store_slug": slug})
        if seller is not None:
            return seller

    seller = await collection.find_one(
        {"store_name": {"$regex": f"^{re.escape(decoded)}$", "$options": "i"}}
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


def _product_to_public(
    product: dict[str, Any],
    seller_by_id: dict[str, dict[str, Any]],
    *,
    buyer_province_id: str | None = None,
    buyer_municipality_id: str | None = None,
) -> MarketplaceProductPublic | None:
    seller_id = product.get("seller_id")
    seller = seller_by_id.get(seller_id)
    if seller is None:
        return None

    pickup_required = False
    pickup_municipality_name = None
    pickup_notice = None
    if buyer_province_id and buyer_municipality_id:
        pickup_required, pickup_municipality_name = _product_pickup_info(
            product,
            seller,
            buyer_province_id,
            buyer_municipality_id,
        )
        if pickup_required:
            if pickup_municipality_name:
                pickup_notice = (
                    f"Sin domicilio a tu municipio · Recoger en {pickup_municipality_name}"
                )
            else:
                pickup_notice = "Sin domicilio a tu municipio"

    global_category_id = product.get("global_category_id") or "otros"
    return MarketplaceProductPublic(
        id=str(product["_id"]),
        global_category_id=global_category_id,
        name=product["name"],
        description=product.get("description"),
        image_url=product["image_url"],
        base_price=float(product["base_price"]),
        base_currency=product["base_currency"],
        accepted_currencies=list(product.get("accepted_currencies") or []),
        offers_delivery=bool(product.get("offers_delivery")),
        is_available=bool(product.get("is_available", True)),
        view_only=False,
        pickup_required=pickup_required,
        pickup_municipality_name=pickup_municipality_name,
        pickup_notice=pickup_notice,
        store=_store_to_public(seller),
        category_name=_display_category_name(global_category_id),
    )


async def _get_visible_sellers(
    province_id: str,
    municipality_id: str,
) -> dict[str, dict[str, Any]]:
    registrations = get_registrations_collection()
    seller_query = {
        "status": "approved",
        "profile_photo_url": {"$exists": True, "$ne": None},
        "category_ids": {"$exists": True, "$not": {"$size": 0}},
        "offers_delivery": {"$exists": True},
        "business_area": {"$exists": True},
        "$or": [
            {
                "business_area.province_id": province_id,
                "business_area.municipality_id": municipality_id,
            },
            {
                "offers_delivery": True,
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
        "profile_photo_url": {"$exists": True, "$ne": None},
        "category_ids": {"$exists": True, "$not": {"$size": 0}},
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


def _marketplace_product_query(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    visibility: list[dict[str, Any]] = []
    if local_seller_ids:
        visibility.append({"seller_id": {"$in": local_seller_ids}})
    if delivery_seller_ids:
        visibility.append(
            {
                "seller_id": {"$in": delivery_seller_ids},
                "offers_delivery": True,
            }
        )
    if pickup_seller_ids:
        visibility.append({"seller_id": {"$in": pickup_seller_ids}})
    if not visibility:
        return {"_id": {"$exists": False}}

    query: dict[str, Any] = {
        "is_available": True,
        "view_only": {"$ne": True},
        "$or": visibility,
    }
    if extra:
        query.update(extra)
    return query


def _seller_store_product_query(
    seller_id: str,
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "seller_id": seller_id,
        "view_only": {"$ne": True},
    }
    if not _seller_is_local_to_municipality(seller, province_id, municipality_id):
        query["offers_delivery"] = True
    if extra:
        query.update(extra)
    return query


def _search_text_filter(query_text: str) -> dict[str, Any] | None:
    normalized = query_text.strip()
    if not normalized:
        return None
    pattern = re.escape(normalized)
    return {
        "$or": [
            {"name": {"$regex": pattern, "$options": "i"}},
            {"description": {"$regex": pattern, "$options": "i"}},
        ],
    }


def _build_marketplace_products_query(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
    global_category_id: str | None = None,
    search_text: str | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if global_category_id:
        extra["global_category_id"] = global_category_id

    query = _marketplace_product_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids,
        extra=extra or None,
    )
    if query.get("_id"):
        return query

    text_filter = _search_text_filter(search_text or "")
    if text_filter:
        query = {"$and": [query, text_filter]}
    return query


def _base_product_filter(seller_ids: list[str]) -> dict[str, Any]:
    return {
        "seller_id": {"$in": seller_ids},
        "is_available": True,
        "view_only": {"$ne": True},
    }


async def _aggregate_category_stats(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    *,
    pickup_seller_ids: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    match_query = _marketplace_product_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids,
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
    return {
        str(item["_id"]): {
            "count": int(item["count"]),
            "popularity": int(item.get("popularity") or 0),
        }
        for item in results
    }


def _sort_category_ids(stats: dict[str, dict[str, int]]) -> list[str]:
    return sorted(
        stats.keys(),
        key=lambda category_id: (
            -stats[category_id]["popularity"],
            business_category_sort_order(category_id),
            category_sort_order(category_id),
        ),
    )


async def _list_category_product_docs(
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    global_category_id: str,
    *,
    pickup_seller_ids: list[str] | None = None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    products_col = get_catalog_products_collection()
    query = _build_marketplace_products_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids,
        global_category_id=global_category_id,
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


async def list_home_feed(
    province_id: str,
    municipality_id: str,
    *,
    limit_per_category: int = DEFAULT_PAGE_SIZE,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceHomeFeedPublic:
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    page_size = _normalize_page_size(limit_per_category)
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
        )

    stats_by_category = await _aggregate_category_stats(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids or None,
    )
    category_ids = _sort_category_ids(stats_by_category)

    sections: list[MarketplaceCategorySectionPublic] = []
    total_products = 0

    for category_id in category_ids:
        total_in_category = stats_by_category[category_id]["count"]
        if total_in_category <= 0:
            continue

        product_docs = await _list_category_product_docs(
            local_seller_ids,
            delivery_seller_ids,
            category_id,
            pickup_seller_ids=pickup_seller_ids or None,
            limit=page_size,
            offset=0,
        )
        products = [
            item
            for doc in product_docs
            if (item := _product_to_public(
                doc,
                seller_by_id,
                buyer_province_id=province_id,
                buyer_municipality_id=municipality_id,
            )) is not None
        ]

        sections.append(
            MarketplaceCategorySectionPublic(
                category_id=category_id,
                category_name=_display_category_name(category_id),
                products=products,
                total_products=total_in_category,
                has_more=total_in_category > len(products),
            )
        )
        total_products += total_in_category

    return MarketplaceHomeFeedPublic(
        province_id=province_id,
        province_name=province_name,
        municipality_id=municipality_id,
        municipality_name=municipality_name,
        sections=sections,
        total_products=total_products,
    )


async def list_category_products(
    province_id: str,
    municipality_id: str,
    global_category_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceCategoryProductsPublic:
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    _ = province_name, municipality_name

    normalized_category_id = _normalize_marketplace_category_id(global_category_id)

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)

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
    )
    total_in_category = stats_by_category.get(normalized_category_id, {}).get("count", 0)

    product_docs = await _list_category_product_docs(
        local_seller_ids,
        delivery_seller_ids,
        normalized_category_id,
        pickup_seller_ids=pickup_seller_ids or None,
        limit=page_size,
        offset=safe_offset,
    )
    products = [
        item
        for doc in product_docs
        if (item := _product_to_public(
            doc,
            seller_by_id,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
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


async def search_products(
    province_id: str,
    municipality_id: str,
    *,
    query: str = "",
    global_category_id: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    municipios_adicionales: list[str] | None = None,
) -> MarketplaceSearchPublic:
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    _ = province_name, municipality_name

    normalized_query = query.strip()
    normalized_category_id = None
    if global_category_id and global_category_id.strip():
        normalized_category_id = _normalize_marketplace_category_id(global_category_id)

    if len(normalized_query) < 2 and not normalized_category_id:
        raise ValueError("Escribe al menos 2 caracteres o elige una categoría.")

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)

    seller_by_id, local_seller_ids, delivery_seller_ids, pickup_seller_ids = (
        await _build_marketplace_seller_context(
            province_id,
            municipality_id,
            municipios_adicionales=municipios_adicionales,
        )
    )

    match_query = _build_marketplace_products_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids or None,
        global_category_id=normalized_category_id,
        search_text=normalized_query,
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


async def _list_store_local_product_docs(
    seller_id: str,
    seller: dict[str, Any],
    province_id: str,
    municipality_id: str,
    category_oid: ObjectId,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    products_col = get_catalog_products_collection()
    query = _seller_store_product_query(
        seller_id,
        seller,
        province_id,
        municipality_id,
        extra={"category_id": category_oid},
    )
    cursor = (
        products_col.find(query)
        .sort(MARKETPLACE_PRODUCT_SORT)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_store_catalog(
    store_ref: str,
    province_id: str,
    municipality_id: str,
    *,
    limit_per_category: int = DEFAULT_PAGE_SIZE,
) -> MarketplaceStoreCatalogPublic:
    _validate_location_ids(province_id, municipality_id)
    page_size = _normalize_page_size(limit_per_category)

    seller = await _resolve_store_catalog_seller(store_ref)
    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    store_public = _store_to_public(seller)
    profile_fields = _store_profile_fields(seller)

    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    category_docs = await categories_col.find({"seller_id": seller_id}).sort("sort_order", 1).to_list(length=None)

    sections: list[MarketplaceStoreLocalSectionPublic] = []
    total_products = 0

    for category_doc in category_docs:
        category_id = str(category_doc["_id"])
        category_oid = category_doc["_id"]
        total_in_category = await products_col.count_documents(
            _seller_store_product_query(
                seller_id,
                seller,
                province_id,
                municipality_id,
                extra={"category_id": category_oid},
            )
        )
        if total_in_category <= 0:
            continue

        product_docs = await _list_store_local_product_docs(
            seller_id,
            seller,
            province_id,
            municipality_id,
            category_oid,
            limit=page_size,
            offset=0,
        )
        products = [
            item
            for doc in product_docs
            if (item := _product_to_public(
                doc,
                seller_by_id,
                buyer_province_id=province_id,
                buyer_municipality_id=municipality_id,
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
) -> MarketplaceStoreCategoryProductsPublic:
    _validate_location_ids(province_id, municipality_id)

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)

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
            extra={"category_id": category_oid},
        )
    )

    product_docs = await _list_store_local_product_docs(
        seller_id,
        seller,
        province_id,
        municipality_id,
        category_oid,
        limit=page_size,
        offset=safe_offset,
    )
    products = [
        item
        for doc in product_docs
        if (item := _product_to_public(
            doc,
            seller_by_id,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
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


async def get_store_public(store_ref: str) -> MarketplaceStorePublic:
    seller = await _find_seller_by_store_ref(store_ref)

    if not is_subscription_active(seller):
        raise ValueError("Tienda no encontrada.")

    if not is_profile_complete(seller):
        raise ValueError("Esta tienda aún no ha completado su perfil público.")

    phone_digits = seller.get("phone")
    if not phone_digits:
        raise ValueError("La tienda no tiene teléfono registrado.")

    return _store_to_public(seller)


JABA_REMOVAL_MESSAGES: dict[str, str] = {
    "deleted": "Ya no está en el catálogo de la tienda.",
    "unavailable": "Está agotado y no se puede comprar por ahora.",
    "view_only": "Es solo para consulta y no admite compra directa.",
    "store_unavailable": "La tienda ya no está disponible o no atiende en tu zona.",
    "no_delivery": "No tiene entrega a domicilio en tu municipio.",
}


def _jaba_removal_message(reason: str) -> str:
    return JABA_REMOVAL_MESSAGES.get(reason, "Ya no se puede comprar.")


def _jaba_product_eligible(
    product: dict[str, Any],
    seller: dict[str, Any] | None,
    *,
    province_id: str | None,
    municipality_id: str | None,
    visible_seller_ids: set[str] | None,
    pickup_seller_ids: set[str] | None = None,
) -> str | None:
    if seller is None:
        return "deleted"

    seller_id = str(seller["_id"])
    if visible_seller_ids is not None:
        if seller_id not in visible_seller_ids:
            return "store_unavailable"
    elif not is_subscription_active(seller) or not is_profile_complete(seller):
        return "store_unavailable"

    if product.get("view_only"):
        return "view_only"

    if not product.get("is_available", True):
        return "unavailable"

    if province_id and municipality_id and visible_seller_ids is not None:
        is_local = _seller_is_local_to_municipality(seller, province_id, municipality_id)
        delivers = product.get("offers_delivery") and _seller_delivers_to_municipality(
            seller,
            province_id,
            municipality_id,
        )
        is_pickup = pickup_seller_ids is not None and seller_id in pickup_seller_ids

        if not is_local and not delivers and not is_pickup:
            return "no_delivery"

    return None


async def sync_jaba_products(payload: JabaSyncRequest) -> JabaSyncPublic:
    if not payload.items:
        return JabaSyncPublic()

    province_id = payload.province_id.strip() if payload.province_id else None
    municipality_id = payload.municipality_id.strip() if payload.municipality_id else None
    visible_sellers: dict[str, dict[str, Any]] | None = None
    visible_seller_ids: set[str] | None = None
    pickup_seller_ids: set[str] | None = None

    if province_id and municipality_id:
        _validate_location_ids(province_id, municipality_id)
        visible_sellers, _, _, pickup_list = await _build_marketplace_seller_context(
            province_id,
            municipality_id,
            municipios_adicionales=payload.municipios_adicionales,
        )
        visible_seller_ids = set(visible_sellers.keys())
        pickup_seller_ids = set(pickup_list)

    products_col = get_catalog_products_collection()
    registrations = get_registrations_collection()

    product_ids: list[str] = []
    names_by_id: dict[str, str] = {}
    for item in payload.items:
        product_id = item.product_id.strip()
        if not product_id or product_id in names_by_id:
            continue
        product_ids.append(product_id)
        names_by_id[product_id] = item.name.strip() or "Producto"

    object_ids: list[ObjectId] = []
    for product_id in product_ids:
        try:
            object_ids.append(ObjectId(product_id))
        except InvalidId:
            continue

    docs_by_id: dict[str, dict[str, Any]] = {}
    if object_ids:
        cursor = products_col.find({"_id": {"$in": object_ids}})
        async for doc in cursor:
            docs_by_id[str(doc["_id"])] = doc

    seller_ids = {doc["seller_id"] for doc in docs_by_id.values()}
    seller_by_id: dict[str, dict[str, Any]] = {}
    if visible_sellers is not None:
        seller_by_id = visible_sellers
    elif seller_ids:
        seller_oids = []
        for seller_id in seller_ids:
            try:
                seller_oids.append(ObjectId(seller_id))
            except InvalidId:
                continue
        if seller_oids:
            seller_docs = await registrations.find({"_id": {"$in": seller_oids}}).to_list(length=None)
            seller_by_id = {str(doc["_id"]): doc for doc in seller_docs}

    valid: list[MarketplaceProductPublic] = []
    removed: list[JabaRemovedProductPublic] = []

    for product_id in product_ids:
        display_name = names_by_id.get(product_id, "Producto")
        doc = docs_by_id.get(product_id)
        if doc is None:
            removed.append(
                JabaRemovedProductPublic(
                    product_id=product_id,
                    name=display_name,
                    reason="deleted",
                    message=_jaba_removal_message("deleted"),
                )
            )
            continue

        seller = seller_by_id.get(doc.get("seller_id"))
        if seller is None and visible_sellers is None:
            try:
                seller = await registrations.find_one({"_id": ObjectId(doc["seller_id"])})
            except InvalidId:
                seller = None

        reason = _jaba_product_eligible(
            doc,
            seller,
            province_id=province_id,
            municipality_id=municipality_id,
            visible_seller_ids=visible_seller_ids,
            pickup_seller_ids=pickup_seller_ids,
        )
        if reason:
            removed.append(
                JabaRemovedProductPublic(
                    product_id=product_id,
                    name=doc.get("name") or display_name,
                    reason=reason,
                    message=_jaba_removal_message(reason),
                )
            )
            continue

        public_sellers = visible_sellers if visible_sellers is not None else seller_by_id
        public = _product_to_public(
            doc,
            public_sellers,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
        )
        if public is None:
            removed.append(
                JabaRemovedProductPublic(
                    product_id=product_id,
                    name=doc.get("name") or display_name,
                    reason="store_unavailable",
                    message=_jaba_removal_message("store_unavailable"),
                )
            )
            continue

        valid.append(public)

    return JabaSyncPublic(valid=valid, removed=removed)
