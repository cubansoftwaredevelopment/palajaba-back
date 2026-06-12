"""
Configura tiendas demo con envíos a otros municipios y productos de prueba
para validar visibilidad por domicilio a nivel producto.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\seed_delivery_visibility_demo.py
  .\\venv\\Scripts\\python.exe scripts\\seed_delivery_visibility_demo.py --wipe
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.services.catalog import ensure_catalog_indexes
from app.utils.datetime import to_utc_naive, utc_now

DELIVERY_TEST_MARKER = "delivery_visibility_test_v1"
PROVINCE_ID = "la-habana"
PROVINCE_NAME = "La Habana"

MUNICIPALITIES = {
    "plaza-de-la-revolucion": "Plaza de la Revolución",
    "centro-habana": "Centro Habana",
    "playa": "Playa",
    "marianao": "Marianao",
}

# Tienda demo existente → municipios a los que envía (sin incluir su propio municipio)
STORE_DELIVERY_TARGETS: dict[str, list[str]] = {
    "Tienducha": ["marianao", "centro-habana", "playa"],
    "Mercado Centro": ["plaza-de-la-revolucion", "marianao", "playa"],
    "Bodega Playa": ["plaza-de-la-revolucion", "centro-habana", "marianao"],
    "Variedades Marianao": ["plaza-de-la-revolucion", "centro-habana", "playa"],
}

TEST_PRODUCTS = [
    {
        "name": "TEST domicilio Sí",
        "offers_delivery": True,
        "base_price": 500,
        "base_currency": "CUP",
    },
    {
        "name": "TEST domicilio No",
        "offers_delivery": False,
        "base_price": 450,
        "base_currency": "CUP",
    },
]


def _delivery_areas(municipality_ids: list[str]) -> list[dict[str, str]]:
    return [
        {
            "province_id": PROVINCE_ID,
            "province_name": PROVINCE_NAME,
            "municipality_id": municipality_id,
            "municipality_name": MUNICIPALITIES[municipality_id],
        }
        for municipality_id in municipality_ids
    ]


async def wipe_test_products() -> None:
    products_col = get_catalog_products_collection()
    result = await products_col.delete_many({"delivery_test_marker": DELIVERY_TEST_MARKER})
    print(f"Productos de prueba eliminados: {result.deleted_count}")


async def configure_store_delivery() -> list[dict]:
    registrations = get_registrations_collection()
    configured: list[dict] = []

    for store_name, targets in STORE_DELIVERY_TARGETS.items():
        seller = await registrations.find_one({"store_name": store_name})
        if seller is None:
            print(f"  ! Omitida «{store_name}»: no existe en la BD")
            continue

        delivery_areas = _delivery_areas(targets)
        await registrations.update_one(
            {"_id": seller["_id"]},
            {
                "$set": {
                    "offers_delivery": True,
                    "delivery_areas": delivery_areas,
                    "updated_at": to_utc_naive(utc_now()),
                }
            },
        )
        area = seller.get("business_area") or {}
        configured.append(
            {
                "store_name": store_name,
                "seller_id": str(seller["_id"]),
                "home_municipality": area.get("municipality_id"),
                "delivery_targets": targets,
            }
        )
        targets_label = ", ".join(MUNICIPALITIES[m] for m in targets)
        print(
            f"  «{store_name}» ({MUNICIPALITIES.get(area.get('municipality_id', ''), '?')}) "
            f"-> envia a: {targets_label}"
        )

    return configured


async def ensure_test_products(stores: list[dict]) -> int:
    products_col = get_catalog_products_collection()
    categories_col = get_catalog_categories_collection()
    now = to_utc_naive(utc_now())
    inserted = 0

    for store in stores:
        seller_id = store["seller_id"]
        category = await categories_col.find_one({"seller_id": seller_id})
        if category is None:
            result = await categories_col.insert_one(
                {
                    "seller_id": seller_id,
                    "name": "Pruebas envío",
                    "product_count": len(TEST_PRODUCTS),
                    "sort_order": 99,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            category_id = result.inserted_id
        else:
            category_id = category["_id"]

        await products_col.delete_many(
            {
                "seller_id": seller_id,
                "delivery_test_marker": DELIVERY_TEST_MARKER,
            }
        )

        global_category_id = "hogar"
        for order, product in enumerate(TEST_PRODUCTS):
            await products_col.insert_one(
                {
                    "seller_id": seller_id,
                    "category_id": category_id,
                    "global_category_id": global_category_id,
                    "name": product["name"],
                    "description": f"Producto de prueba — {store['store_name']}",
                    "image_url": f"https://picsum.photos/seed/{store['store_name']}-{order}/500/500",
                    "base_price": float(product["base_price"]),
                    "base_currency": product["base_currency"],
                    "accepted_currencies": [],
                    "offers_delivery": product["offers_delivery"],
                    "view_only": False,
                    "is_available": True,
                    "sort_order": 100 + order,
                    "popularity": 200 if product["offers_delivery"] else 10,
                    "delivery_test_marker": DELIVERY_TEST_MARKER,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            inserted += 1

        print(f"  Productos TEST en «{store['store_name']}»: {len(TEST_PRODUCTS)}")

    return inserted


async def main(*, wipe: bool) -> None:
    await connect_to_mongo()
    await ensure_catalog_indexes()

    print("Configurando envíos cruzados entre municipios (La Habana)…\n")
    if wipe:
        await wipe_test_products()

    stores = await configure_store_delivery()
    if not stores:
        print("\nNo hay tiendas demo. Ejecuta antes: scripts/seed_production_demo.py --force")
        await close_mongo_connection()
        return

    print("\nInsertando productos TEST (domicilio Sí / No)…")
    count = await ensure_test_products(stores)
    print(f"\nListo: {len(stores)} tiendas, {count} productos de prueba.")
    print("Ejecuta: scripts/test_delivery_visibility.py")
    await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed de prueba para visibilidad por domicilio")
    parser.add_argument("--wipe", action="store_true", help="Elimina solo productos TEST anteriores")
    args = parser.parse_args()
    asyncio.run(main(wipe=args.wipe))
