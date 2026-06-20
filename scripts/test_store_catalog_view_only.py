"""
Tests: productos «solo vista» deben aparecer en el catálogo público de la tienda,
pero no en marketplace/home.

Uso (desde backend/):
  python scripts/test_store_catalog_view_only.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bson import ObjectId

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.services.marketplace import (
    _build_marketplace_products_query,
    _get_visible_sellers,
    _marketplace_product_query,
    _product_to_public,
    _seller_is_local_to_municipality,
    _seller_store_product_query,
    _split_sellers_by_locality,
    get_store_catalog,
    list_store_category_products,
)
from app.utils.datetime import to_utc_naive, utc_now

MARKER = "view_only_catalog_test_v1"
PROVINCE_ID = "la-habana"
MUNICIPALITY_ID = "playa"
STORE_NAME = "TEST ViewOnly Catalog Store"
PRODUCT_VIEW_ONLY = "TEST producto solo vista"
PRODUCT_PURCHASABLE = "TEST producto comprable"


def _seller_doc(seller_id: ObjectId) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": STORE_NAME,
        "store_slug": "test-viewonly-catalog-store",
        "phone": "59999999",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=5),
        "subscription_ends_at": now + timedelta(days=25),
        "delivery_areas": [],
    }


def _product_doc(
    *,
    seller_id: str,
    category_id: ObjectId,
    name: str,
    view_only: bool,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "seller_id": seller_id,
        "category_id": category_id,
        "name": name,
        "description": "Test",
        "image_url": "https://example.com/product.jpg",
        "base_price": 100.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": False,
        "is_available": True,
        "view_only": view_only,
        "global_category_id": "otros",
        "view_only_catalog_test_marker": MARKER,
        "created_at": now,
        "updated_at": now,
    }


def test_seller_store_query_does_not_exclude_view_only() -> None:
    seller = _seller_doc(ObjectId())
    query = _seller_store_product_query(
        str(seller["_id"]),
        seller,
        PROVINCE_ID,
        MUNICIPALITY_ID,
    )
    assert "view_only" not in query, "El catálogo público no debe filtrar view_only"


def test_marketplace_query_still_excludes_view_only() -> None:
    query = _marketplace_product_query(["seller-1"], [])
    assert query.get("view_only") == {"$ne": True}


def test_product_to_public_preserves_view_only_flag() -> None:
    seller = _seller_doc(ObjectId())
    seller_id = str(seller["_id"])
    seller_by_id = {seller_id: seller}
    product = _product_doc(
        seller_id=seller_id,
        category_id=ObjectId(),
        name=PRODUCT_VIEW_ONLY,
        view_only=True,
    )
    product["_id"] = ObjectId()

    public = _product_to_public(
        product,
        seller_by_id,
        buyer_province_id=PROVINCE_ID,
        buyer_municipality_id=MUNICIPALITY_ID,
    )
    assert public is not None
    assert public.view_only is True
    assert public.name == PRODUCT_VIEW_ONLY


async def _seed_test_data() -> tuple[str, ObjectId, ObjectId, ObjectId]:
    registrations = get_registrations_collection()
    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    seller_id = ObjectId()
    category_id = ObjectId()
    view_only_id = ObjectId()
    purchasable_id = ObjectId()
    seller_id_str = str(seller_id)

    await registrations.insert_one(_seller_doc(seller_id))
    await categories_col.insert_one(
        {
            "_id": category_id,
            "seller_id": seller_id_str,
            "name": "TEST categoría view only",
            "sort_order": 0,
            "view_only_catalog_test_marker": MARKER,
        }
    )
    await products_col.insert_one(
        {
            **_product_doc(
                seller_id=seller_id_str,
                category_id=category_id,
                name=PRODUCT_VIEW_ONLY,
                view_only=True,
            ),
            "_id": view_only_id,
        }
    )
    await products_col.insert_one(
        {
            **_product_doc(
                seller_id=seller_id_str,
                category_id=category_id,
                name=PRODUCT_PURCHASABLE,
                view_only=False,
            ),
            "_id": purchasable_id,
        }
    )
    return seller_id_str, category_id, view_only_id, purchasable_id


async def _cleanup_test_data() -> None:
    registrations = get_registrations_collection()
    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    await products_col.delete_many({"view_only_catalog_test_marker": MARKER})
    await categories_col.delete_many({"view_only_catalog_test_marker": MARKER})
    await registrations.delete_many({"store_name": STORE_NAME})


async def test_store_catalog_includes_view_only_product() -> None:
    seller_id, category_id, view_only_id, purchasable_id = await _seed_test_data()
    try:
        catalog = await get_store_catalog(
            "test-viewonly-catalog-store",
            PROVINCE_ID,
            MUNICIPALITY_ID,
            limit_per_category=20,
        )
        product_ids = {
            product.id
            for section in catalog.sections
            for product in section.products
        }
        assert str(view_only_id) in product_ids, "El catálogo público debe incluir productos solo vista"
        assert str(purchasable_id) in product_ids, "El catálogo público debe incluir productos comprables"

        view_only_product = next(
            product
            for section in catalog.sections
            for product in section.products
            if product.id == str(view_only_id)
        )
        assert view_only_product.view_only is True
    finally:
        await _cleanup_test_data()


async def test_list_store_category_products_includes_view_only() -> None:
    seller_id, category_id, view_only_id, purchasable_id = await _seed_test_data()
    try:
        page = await list_store_category_products(
            "test-viewonly-catalog-store",
            PROVINCE_ID,
            MUNICIPALITY_ID,
            str(category_id),
            limit=20,
            offset=0,
        )
        product_ids = {product.id for product in page.products}
        assert str(view_only_id) in product_ids
        assert page.total_products >= 2
    finally:
        await _cleanup_test_data()


async def test_marketplace_still_hides_view_only_product() -> None:
    seller_id, category_id, view_only_id, purchasable_id = await _seed_test_data()
    try:
        seller_by_id = await _get_visible_sellers(PROVINCE_ID, MUNICIPALITY_ID)
        assert seller_id in seller_by_id, "La tienda de prueba debe ser visible en marketplace"

        local_ids, delivery_ids = _split_sellers_by_locality(
            seller_by_id,
            PROVINCE_ID,
            MUNICIPALITY_ID,
        )
        query = _build_marketplace_products_query(local_ids, delivery_ids)
        products_col = get_catalog_products_collection()

        view_only_visible = await products_col.count_documents(
            {**query, "_id": view_only_id}
        )
        purchasable_visible = await products_col.count_documents(
            {**query, "_id": purchasable_id}
        )

        assert view_only_visible == 0, "Marketplace no debe mostrar productos solo vista"
        assert purchasable_visible == 1, "Marketplace debe seguir mostrando productos comprables"
    finally:
        await _cleanup_test_data()


async def test_store_query_count_includes_view_only() -> None:
    seller_id, category_id, view_only_id, purchasable_id = await _seed_test_data()
    try:
        seller = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
        assert seller is not None

        store_query = _seller_store_product_query(
            seller_id,
            seller,
            PROVINCE_ID,
            MUNICIPALITY_ID,
            extra={"category_id": category_id},
        )
        products_col = get_catalog_products_collection()

        assert await products_col.count_documents({**store_query, "_id": view_only_id}) == 1
        assert await products_col.count_documents({**store_query, "_id": purchasable_id}) == 1
    finally:
        await _cleanup_test_data()


async def main() -> None:
    test_seller_store_query_does_not_exclude_view_only()
    test_marketplace_query_still_excludes_view_only()
    test_product_to_public_preserves_view_only_flag()

    await connect_to_mongo()
    try:
        await test_store_query_count_includes_view_only()
        await test_store_catalog_includes_view_only_product()
        await test_list_store_category_products_includes_view_only()
        await test_marketplace_still_hides_view_only_product()
    finally:
        await _cleanup_test_data()
        await close_mongo_connection()

    print("OK: store catalog view_only tests passed")


if __name__ == "__main__":
    asyncio.run(main())
