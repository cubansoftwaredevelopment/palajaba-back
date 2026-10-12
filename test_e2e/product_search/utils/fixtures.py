"""Datos propios del e2e de autocompletado de productos con pedidos."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import seller_auth_headers
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "product_search_e2e_v1"


def store_name(seller_id: str) -> str:
    return f"TEST Busqueda {seller_id}"


def _unique_phone(seed: ObjectId) -> str:
    return f"{int(str(seed), 16) % 100000000:08d}"


def seller_document(*, seller_id: ObjectId) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name(str(seller_id)),
        "store_slug": f"test-busqueda-{seller_id}",
        "transfer_id": f"TEST-SEARCH-{seller_id}",
        "phone": _unique_phone(seller_id),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        "created_at": now,
        "updated_at": now,
        "product_search_e2e_marker": MARKER,
    }


def category_document(*, seller_id: str, category_id: ObjectId, name: str) -> dict:
    return {
        "_id": category_id,
        "seller_id": seller_id,
        "name": name,
        "sort_order": 0,
        "product_search_e2e_marker": MARKER,
    }


def product_document(
    *,
    seller_id: str,
    product_id: ObjectId,
    category_id: ObjectId,
    name: str,
    is_available: bool = True,
    view_only: bool = False,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": product_id,
        "seller_id": seller_id,
        "category_id": category_id,
        "name": name,
        "description": "Producto de prueba",
        "image_url": "https://example.com/product.jpg",
        "base_price": 100.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": False,
        "is_available": is_available,
        "view_only": view_only,
        "global_category_id": "otros",
        "popularity": 0,
        "sort_order": 0,
        "stock_quantity": 4,
        "created_at": now,
        "updated_at": now,
        "product_search_e2e_marker": MARKER,
    }


def order_document(*, seller_id: str, product_id: str, name: str) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "seller_id": seller_id,
        "store_name": store_name(seller_id),
        "status": "pending_confirmation",
        "items": [
            {
                "product_id": product_id,
                "name": name,
                "quantity": 1,
                "unit_price": 100.0,
                "currency": "CUP",
            }
        ],
        "created_at": now,
        "updated_at": now,
        "product_search_e2e_marker": MARKER,
    }


async def cleanup() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()
    orders = get_orders_collection()
    seller_ids = [
        str(doc["_id"])
        async for doc in registrations.find(
            {"product_search_e2e_marker": MARKER},
            {"_id": 1},
        )
    ]
    if seller_ids:
        await orders.delete_many({"seller_id": {"$in": seller_ids}})
        await products.delete_many({"seller_id": {"$in": seller_ids}})
        await categories.delete_many({"seller_id": {"$in": seller_ids}})
    await orders.delete_many({"product_search_e2e_marker": MARKER})
    await products.delete_many({"product_search_e2e_marker": MARKER})
    await categories.delete_many({"product_search_e2e_marker": MARKER})
    await registrations.delete_many({"product_search_e2e_marker": MARKER})


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_search_catalog() -> dict[str, str]:
    seller_id = ObjectId()
    empty_seller_id = ObjectId()
    despensa_id = ObjectId()
    bebidas_id = ObjectId()
    arroz_id = ObjectId()
    cafe_id = ObjectId()
    jamon_id = ObjectId()
    aceite_id = ObjectId()
    frijoles_id = ObjectId()
    seller = str(seller_id)

    await get_registrations_collection().insert_many(
        [
            seller_document(seller_id=seller_id),
            seller_document(seller_id=empty_seller_id),
        ]
    )
    await get_catalog_categories_collection().insert_many(
        [
            category_document(seller_id=seller, category_id=despensa_id, name="Despensa"),
            category_document(seller_id=seller, category_id=bebidas_id, name="Bebidas"),
        ]
    )
    await get_catalog_products_collection().insert_many(
        [
            product_document(
                seller_id=seller,
                product_id=arroz_id,
                category_id=despensa_id,
                name="Arroz Premium",
            ),
            product_document(
                seller_id=seller,
                product_id=cafe_id,
                category_id=bebidas_id,
                name="Café",
            ),
            product_document(
                seller_id=seller,
                product_id=jamon_id,
                category_id=despensa_id,
                name="Jamón",
            ),
            product_document(
                seller_id=seller,
                product_id=aceite_id,
                category_id=despensa_id,
                name="Aceite",
                view_only=True,
            ),
            product_document(
                seller_id=seller,
                product_id=frijoles_id,
                category_id=despensa_id,
                name="Frijoles",
                is_available=False,
            ),
        ]
    )
    await get_orders_collection().insert_many(
        [
            order_document(seller_id=seller, product_id=str(arroz_id), name="Arroz Premium"),
            order_document(seller_id=seller, product_id=str(cafe_id), name="Café"),
            order_document(seller_id=seller, product_id=str(aceite_id), name="Aceite"),
            order_document(seller_id=seller, product_id=str(frijoles_id), name="Frijoles"),
        ]
    )
    return {
        "seller_id": seller,
        "empty_seller_id": str(empty_seller_id),
    }


def seed_search_catalog() -> dict[str, str]:
    return run_db(_seed_search_catalog)


def headers_for(seller_id: str) -> dict[str, str]:
    return seller_auth_headers(seller_id=seller_id, store_name=store_name(seller_id))
