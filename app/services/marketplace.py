from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.database import get_catalog_products_collection, get_registrations_collection
from app.schemas.marketplace import (
    MarketplaceCategoryProductsPublic,
    MarketplaceCategorySectionPublic,
    MarketplaceHomeFeedPublic,
    MarketplaceProductPublic,
    MarketplaceStorePublic,
)
from app.services.cuba_locations import MUNICIPALITIES_BY_PROVINCE, PROVINCE_NAMES
from app.services.product_categories import REVOLICO_PRODUCT_CATEGORIES, category_name, category_sort_order
from app.services.product_popularity import MARKETPLACE_PRODUCT_SORT
from app.services.seller_profile import is_profile_complete
from app.services.subscriptions import is_subscription_active
from app.utils.phone import phone_display

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


def _normalize_page_size(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))


def _product_to_public(
    product: dict[str, Any],
    seller_by_id: dict[str, dict[str, Any]],
) -> MarketplaceProductPublic | None:
    seller_id = product.get("seller_id")
    seller = seller_by_id.get(seller_id)
    if seller is None:
        return None

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
        view_only=False,
        store=MarketplaceStorePublic(
            id=seller_id,
            store_name=seller["store_name"],
            phone=phone_display(seller["phone"]),
            profile_photo_url=seller.get("profile_photo_url"),
        ),
        category_name=category_name(global_category_id),
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


def _base_product_filter(seller_ids: list[str]) -> dict[str, Any]:
    return {
        "seller_id": {"$in": seller_ids},
        "is_available": True,
        "view_only": {"$ne": True},
    }


async def _aggregate_category_stats(
    seller_ids: list[str],
) -> dict[str, dict[str, int]]:
    if not seller_ids:
        return {}

    products_col = get_catalog_products_collection()
    pipeline = [
        {"$match": _base_product_filter(seller_ids)},
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
            category_sort_order(category_id),
        ),
    )


async def _list_category_product_docs(
    seller_ids: list[str],
    global_category_id: str,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    products_col = get_catalog_products_collection()
    query = {
        **_base_product_filter(seller_ids),
        "global_category_id": global_category_id,
    }
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
) -> MarketplaceHomeFeedPublic:
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    page_size = _normalize_page_size(limit_per_category)
    seller_by_id = await _get_visible_sellers(province_id, municipality_id)
    seller_ids = list(seller_by_id.keys())

    if not seller_ids:
        return MarketplaceHomeFeedPublic(
            province_id=province_id,
            province_name=province_name,
            municipality_id=municipality_id,
            municipality_name=municipality_name,
            sections=[],
            total_products=0,
        )

    stats_by_category = await _aggregate_category_stats(seller_ids)
    category_ids = _sort_category_ids(stats_by_category)

    sections: list[MarketplaceCategorySectionPublic] = []
    total_products = 0

    for category_id in category_ids:
        total_in_category = stats_by_category[category_id]["count"]
        if total_in_category <= 0:
            continue

        product_docs = await _list_category_product_docs(
            seller_ids,
            category_id,
            limit=page_size,
            offset=0,
        )
        products = [
            item
            for doc in product_docs
            if (item := _product_to_public(doc, seller_by_id)) is not None
        ]

        sections.append(
            MarketplaceCategorySectionPublic(
                category_id=category_id,
                category_name=category_name(category_id),
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
) -> MarketplaceCategoryProductsPublic:
    province_name, municipality_name = _validate_location_ids(province_id, municipality_id)
    _ = province_name, municipality_name

    normalized_category_id = global_category_id.strip().lower()
    known_ids = {item["id"] for item in REVOLICO_PRODUCT_CATEGORIES}
    if normalized_category_id not in known_ids:
        raise ValueError("Categoría no válida.")

    page_size = _normalize_page_size(limit)
    safe_offset = max(0, offset)

    seller_by_id = await _get_visible_sellers(province_id, municipality_id)
    seller_ids = list(seller_by_id.keys())

    if not seller_ids:
        return MarketplaceCategoryProductsPublic(
            category_id=normalized_category_id,
            category_name=category_name(normalized_category_id),
            products=[],
            total_products=0,
            limit=page_size,
            offset=safe_offset,
            has_more=False,
        )

    stats_by_category = await _aggregate_category_stats(seller_ids)
    total_in_category = stats_by_category.get(normalized_category_id, {}).get("count", 0)

    product_docs = await _list_category_product_docs(
        seller_ids,
        normalized_category_id,
        limit=page_size,
        offset=safe_offset,
    )
    products = [
        item
        for doc in product_docs
        if (item := _product_to_public(doc, seller_by_id)) is not None
    ]

    loaded = safe_offset + len(products)
    return MarketplaceCategoryProductsPublic(
        category_id=normalized_category_id,
        category_name=category_name(normalized_category_id),
        products=products,
        total_products=total_in_category,
        limit=page_size,
        offset=safe_offset,
        has_more=loaded < total_in_category,
    )


async def get_store_public(store_id: str) -> MarketplaceStorePublic:
    try:
        seller_oid = ObjectId(store_id.strip())
    except InvalidId as exc:
        raise ValueError("Tienda no válida.") from exc

    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if seller is None:
        raise ValueError("Tienda no encontrada.")

    phone_digits = seller.get("phone")
    if not phone_digits:
        raise ValueError("La tienda no tiene teléfono registrado.")

    return MarketplaceStorePublic(
        id=str(seller["_id"]),
        store_name=seller["store_name"],
        phone=phone_display(phone_digits),
        profile_photo_url=seller.get("profile_photo_url"),
    )
