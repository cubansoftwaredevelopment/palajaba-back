"""
Pobla la base de datos con tiendas y productos de demostración (producción o local).

Crea 4 tiendas aprobadas con perfil completo y 100 productos (25 por tienda),
visibles en el marketplace de La Habana.

Uso (desde backend/, con .env apuntando a la BD deseada):
  .\\venv\\Scripts\\python.exe scripts\\seed_production_demo.py
  .\\venv\\Scripts\\python.exe scripts\\seed_production_demo.py --wipe
  .\\venv\\Scripts\\python.exe scripts\\seed_production_demo.py --dry-run
  .\\venv\\Scripts\\python.exe scripts\\seed_production_demo.py --force

Credenciales de las tiendas demo (login por nombre de tienda):
  Contraseña: Demo2026!
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.security import hash_password
from app.services.catalog import ensure_catalog_indexes
from app.services.categories import ensure_category_seed
from app.services.product_categories import ensure_product_category_seed
from app.utils.datetime import to_utc_naive, utc_now

DEMO_MARKER = "palajaba_demo_seed_v1"
DEMO_PASSWORD = "Demo2026!"

LOCAL_CATEGORY_NAMES = ["Destacados", "Ofertas", "Novedades", "Más vendidos"]

PRODUCT_ADJECTIVES = [
    "Clásico",
    "Premium",
    "Económico",
    "Recargable",
    "Portátil",
    "Importado",
    "Nacional",
    "Nuevo",
    "Oferta",
    "Resistente",
]

PRODUCT_NOUNS = [
    "Licuadora",
    "Ventilador",
    "Auriculares",
    "Cargador",
    "Camiseta",
    "Pantalón",
    "Zapatillas",
    "Sartén",
    "Olla",
    "Lámpara",
    "Reloj",
    "Mochila",
    "Crema facial",
    "Jabón",
    "Pelota",
    "Raqueta",
    "Collar",
    "Libro",
    "Teclado",
    "Mouse",
    "Silla",
    "Mesa",
    "Martillo",
    "Taladro",
    "Arroz",
    "Aceite",
    "Café",
    "Leche",
    "Galletas",
    "Juguete",
]

STORES = [
    {
        "store_name": "Tienducha",
        "phone": "55100001",
        "transfer_id": "DEMO-SEED-001",
        "category_ids": ["hogar", "tecnologia"],
        "municipality_id": "plaza-de-la-revolucion",
        "municipality_name": "Plaza de la Revolución",
        "biography": "Electrodomésticos y despensa en el Vedado.",
    },
    {
        "store_name": "Mercado Centro",
        "phone": "55100002",
        "transfer_id": "DEMO-SEED-002",
        "category_ids": ["comida", "moda"],
        "municipality_id": "centro-habana",
        "municipality_name": "Centro Habana",
        "biography": "Moda y alimentos en el corazón de la ciudad.",
    },
    {
        "store_name": "Bodega Playa",
        "phone": "55100003",
        "transfer_id": "DEMO-SEED-003",
        "category_ids": ["comida", "belleza"],
        "municipality_id": "playa",
        "municipality_name": "Playa",
        "biography": "Despensa y cuidado personal cerca del malecón.",
    },
    {
        "store_name": "Variedades Marianao",
        "phone": "55100004",
        "transfer_id": "DEMO-SEED-004",
        "category_ids": ["tecnologia", "hogar", "otros"],
        "municipality_id": "marianao",
        "municipality_name": "Marianao",
        "biography": "Tecnología, hogar y más en Marianao.",
    },
]

PROVINCE_ID = "la-habana"
PROVINCE_NAME = "La Habana"


def _image_url(seed: str) -> str:
    return f"https://picsum.photos/seed/{seed}/500/500"


def _profile_photo_url(store_slug: str) -> str:
    return _image_url(f"profile-{store_slug}")


def _product_name(index: int) -> str:
    adj = PRODUCT_ADJECTIVES[index % len(PRODUCT_ADJECTIVES)]
    noun = PRODUCT_NOUNS[(index * 3) % len(PRODUCT_NOUNS)]
    return f"{adj} {noun} {index + 1}"


def _product_price(index: int) -> tuple[float, str, list[str]]:
    if index % 5 == 0:
        return round(5 + (index % 40) * 2.5, 2), "USD", ["CUP"]
    if index % 7 == 0:
        return float(800 + (index % 50) * 120), "CUP", ["USD", "MLC"]
    return float(150 + (index % 80) * 95), "CUP", []


async def wipe_demo_data() -> None:
    registrations = get_registrations_collection()
    products = get_catalog_products_collection()

    demo_sellers = await registrations.find({"demo_seed": DEMO_MARKER}).to_list(length=None)
    seller_ids = [str(doc["_id"]) for doc in demo_sellers]

    if seller_ids:
        deleted_products = await products.delete_many({"seller_id": {"$in": seller_ids}})
        print(f"Productos demo eliminados: {deleted_products.deleted_count}")

    deleted_regs = await registrations.delete_many({"demo_seed": DEMO_MARKER})
    print(f"Tiendas demo eliminadas: {deleted_regs.deleted_count}")


async def upsert_store(store: dict, *, dry_run: bool, force: bool) -> str | None:
    registrations = get_registrations_collection()
    now = to_utc_naive(utc_now())
    subscription_end = now + timedelta(days=365)
    store_slug = store["store_name"].lower().replace(" ", "-")

    existing = await registrations.find_one({"store_name": store["store_name"]})
    if existing and existing.get("demo_seed") != DEMO_MARKER and not force:
        print(
            f"  ! «{store['store_name']}» ya existe. Usa --force para actualizarla y poblar productos."
        )
        return None

    document = {
        "transfer_id": store["transfer_id"],
        "store_name": store["store_name"],
        "phone": store["phone"],
        "password_hash": hash_password(DEMO_PASSWORD),
        "billing_period": "yearly",
        "status": "approved",
        "subscription_starts_at": now,
        "subscription_ends_at": subscription_end,
        "rejection_reason": None,
        "approved_at": now,
        "payment_amount_cup": 10000,
        "profile_photo_url": _profile_photo_url(store_slug),
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": PROVINCE_NAME,
            "municipality_id": store["municipality_id"],
            "municipality_name": store["municipality_name"],
        },
        "biography": store["biography"],
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": store["category_ids"],
        "offers_delivery": True,
        "profile_completed_at": now,
        "demo_seed": DEMO_MARKER,
        "updated_at": now,
    }

    if existing:
        seller_id = str(existing["_id"])
        if dry_run:
            print(f"  [dry-run] Actualizaría tienda «{store['store_name']}» ({seller_id})")
            return seller_id
        await registrations.update_one({"_id": existing["_id"]}, {"$set": document})
        print(f"  Tienda actualizada: «{store['store_name']}» ({seller_id})")
        return seller_id

    document["created_at"] = now
    document["business_location"] = None

    if dry_run:
        print(f"  [dry-run] Crearía tienda «{store['store_name']}»")
        return "dry-run-seller-id"

    result = await registrations.insert_one(document)
    seller_id = str(result.inserted_id)
    print(f"  Tienda creada: «{store['store_name']}» ({seller_id})")
    return seller_id


async def ensure_local_categories(seller_id: str, *, dry_run: bool) -> list:
    if dry_run:
        return []

    categories_col = get_catalog_categories_collection()
    existing = await categories_col.find({"seller_id": seller_id}).to_list(length=None)
    if existing:
        return existing

    now = to_utc_naive(utc_now())
    created = []
    for order, name in enumerate(LOCAL_CATEGORY_NAMES[:3]):
        doc = {
            "seller_id": seller_id,
            "name": name,
            "product_count": 0,
            "sort_order": order,
            "created_at": now,
            "updated_at": now,
        }
        result = await categories_col.insert_one(doc)
        doc["_id"] = result.inserted_id
        created.append(doc)
    return created


async def seed_products(
    seller_id: str,
    store_name: str,
    business_category_ids: list[str],
    local_categories: list,
    *,
    products_per_store: int,
    dry_run: bool,
    start_index: int,
) -> int:
    if dry_run:
        print(f"    [dry-run] {products_per_store} productos para «{store_name}»")
        return products_per_store

    products_col = get_catalog_products_collection()
    await products_col.delete_many({"seller_id": seller_id, "demo_seed": DEMO_MARKER})

    now = to_utc_naive(utc_now())
    store_slug = store_name.lower().replace(" ", "-")
    inserted = 0

    if not local_categories or not business_category_ids:
        print("    ! Sin categorías locales o de negocio; se omitieron productos.")
        return 0

    for offset in range(products_per_store):
        index = start_index + offset
        global_category_id = business_category_ids[index % len(business_category_ids)]
        local_category = local_categories[offset % len(local_categories)]
        price, currency, accepted = _product_price(index)
        seed = f"{store_slug}-product-{index}"

        product_doc = {
            "seller_id": seller_id,
            "category_id": local_category["_id"],
            "global_category_id": global_category_id,
            "name": _product_name(index),
            "description": f"Producto de demostración para {store_name}.",
            "image_url": _image_url(seed),
            "base_price": price,
            "base_currency": currency,
            "accepted_currencies": accepted,
            "offers_delivery": index % 4 != 0,
            "view_only": index % 17 == 0,
            "is_available": index % 11 != 0,
            "sort_order": offset,
            "popularity": random.randint(0, 20),
            "demo_seed": DEMO_MARKER,
            "created_at": now,
            "updated_at": now,
        }
        await products_col.insert_one(product_doc)
        inserted += 1

    categories_col = get_catalog_categories_collection()
    for local_category in local_categories:
        count = await products_col.count_documents(
            {"seller_id": seller_id, "category_id": local_category["_id"]}
        )
        await categories_col.update_one(
            {"_id": local_category["_id"]},
            {"$set": {"product_count": count}},
        )

    print(f"    {inserted} productos en «{store_name}»")
    return inserted


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo: tiendas + productos")
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Elimina antes las tiendas/productos marcados con demo_seed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra qué haría sin escribir en la base de datos",
    )
    parser.add_argument("--stores", type=int, default=4, help="Número de tiendas (máx. 4)")
    parser.add_argument(
        "--products-per-store",
        type=int,
        default=25,
        help="Productos por tienda (4×25 = 100 por defecto)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actualiza tiendas que ya existan con el mismo nombre (ej. Tienducha)",
    )
    args = parser.parse_args()

    store_configs = STORES[: max(1, min(args.stores, len(STORES)))]

    await connect_to_mongo()
    await ensure_category_seed()
    await ensure_product_category_seed()
    await ensure_catalog_indexes()

    print(f"Base de datos: seed demo ({len(store_configs)} tiendas)")
    if args.dry_run:
        print("Modo dry-run: no se escribirá en MongoDB.\n")

    if args.wipe and not args.dry_run:
        print("Eliminando datos demo anteriores…")
        await wipe_demo_data()
        print()

    total_products = 0
    product_index = 0

    for store in store_configs:
        print(f"\n«{store['store_name']}» — {store['municipality_name']}, {PROVINCE_NAME}")
        seller_id = await upsert_store(store, dry_run=args.dry_run, force=args.force)
        if seller_id is None:
            continue

        local_categories = await ensure_local_categories(seller_id, dry_run=args.dry_run)
        count = await seed_products(
            seller_id,
            store["store_name"],
            store["category_ids"],
            local_categories,
            products_per_store=args.products_per_store,
            dry_run=args.dry_run,
            start_index=product_index,
        )
        total_products += count
        product_index += args.products_per_store

    print("\n--- Resumen ---")
    print(f"Tiendas: {len(store_configs)}")
    print(f"Productos: {total_products}")
    print(f"Contraseña de todas las tiendas demo: {DEMO_PASSWORD}")
    print("Login: nombre de tienda + contraseña (pantalla vendedor)")
    print(
        f"Marketplace: provincia {PROVINCE_NAME}, municipio según cada tienda "
        "(ej. Plaza de la Revolución para Tienducha)."
    )

    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
