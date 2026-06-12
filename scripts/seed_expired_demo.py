"""
Crea o actualiza una tienda demo con suscripción vencida para probar el flujo local.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\seed_expired_demo.py
  .\\venv\\Scripts\\python.exe scripts\\seed_expired_demo.py --wipe

Credenciales:
  Tienda: Tienda Vencida  (o teléfono 55100005)
  Contraseña: Demo2026!
"""

from __future__ import annotations

import argparse
import asyncio
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
from app.utils.store_slug import store_name_to_slug

from seed_production_demo import (
    DEMO_PASSWORD,
    LOCAL_CATEGORY_NAMES,
    PROVINCE_ID,
    PROVINCE_NAME,
    _image_url,
    _product_name,
    _product_price,
    _profile_photo_url,
    ensure_local_categories,
)

EXPIRED_MARKER = "palajaba_expired_demo_v1"
STORE_NAME = "Tienda Vencida"
STORE_PHONE = "55100005"
PRODUCTS_COUNT = 8


async def wipe_expired_demo() -> None:
    registrations = get_registrations_collection()
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()

    demo_sellers = await registrations.find({"demo_seed": EXPIRED_MARKER}).to_list(length=None)
    seller_ids = [str(doc["_id"]) for doc in demo_sellers]

    if seller_ids:
        deleted_products = await products.delete_many({"seller_id": {"$in": seller_ids}})
        deleted_categories = await categories.delete_many({"seller_id": {"$in": seller_ids}})
        print(f"Productos eliminados: {deleted_products.deleted_count}")
        print(f"Categorías eliminadas: {deleted_categories.deleted_count}")

    deleted_regs = await registrations.delete_many({"demo_seed": EXPIRED_MARKER})
    print(f"Tiendas vencidas demo eliminadas: {deleted_regs.deleted_count}")


async def seed_expired_store(*, dry_run: bool) -> None:
    registrations = get_registrations_collection()
    now = to_utc_naive(utc_now())
    subscription_end = now - timedelta(days=15)
    subscription_start = subscription_end - timedelta(days=30)
    approved_at = subscription_start
    store_slug = store_name_to_slug(STORE_NAME)

    document = {
        "transfer_id": "DEMO-EXPIRED-001",
        "store_name": STORE_NAME,
        "store_slug": store_slug,
        "phone": STORE_PHONE,
        "password_hash": hash_password(DEMO_PASSWORD),
        "plan_tier": "standard",
        "billing_period": "monthly",
        "status": "expired",
        "subscription_starts_at": subscription_start,
        "subscription_ends_at": subscription_end,
        "rejection_reason": None,
        "approved_at": approved_at,
        "payment_amount_cup": 2,
        "profile_photo_url": _profile_photo_url(store_slug),
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": PROVINCE_NAME,
            "municipality_id": "plaza-de-la-revolucion",
            "municipality_name": "Plaza de la Revolución",
        },
        "biography": "Tienda demo con plan vencido para probar el panel y la vista pública.",
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": ["hogar", "tecnologia"],
        "offers_delivery": True,
        "profile_completed_at": approved_at,
        "demo_seed": EXPIRED_MARKER,
        "updated_at": now,
    }

    existing = await registrations.find_one({"demo_seed": EXPIRED_MARKER})

    if dry_run:
        action = "Actualizaría" if existing else "Crearía"
        print(f"[dry-run] {action} «{STORE_NAME}» con vencimiento {subscription_end.date()}")
        return

    if existing:
        seller_id = str(existing["_id"])
        await registrations.update_one({"_id": existing["_id"]}, {"$set": document})
        print(f"Tienda actualizada: «{STORE_NAME}» ({seller_id})")
    else:
        document["created_at"] = now
        document["business_location"] = None
        result = await registrations.insert_one(document)
        seller_id = str(result.inserted_id)
        print(f"Tienda creada: «{STORE_NAME}» ({seller_id})")

    products_col = get_catalog_products_collection()
    await products_col.delete_many({"seller_id": seller_id, "demo_seed": EXPIRED_MARKER})

    local_categories = await ensure_local_categories(seller_id, dry_run=False)
    if not local_categories:
        categories_col = get_catalog_categories_collection()
        local_categories = await categories_col.find({"seller_id": seller_id}).to_list(length=None)

    start_index = 900
    inserted = 0
    for index in range(PRODUCTS_COUNT):
        local_category = local_categories[index % len(local_categories)]
        price, currency, accepted = _product_price(start_index + index)
        product_doc = {
            "seller_id": seller_id,
            "category_id": local_category["_id"],
            "global_category_id": document["category_ids"][index % len(document["category_ids"])],
            "name": f"Vencido · {_product_name(start_index + index)}",
            "description": "Producto demo de tienda con suscripción vencida.",
            "image_url": _image_url(f"expired-{store_slug}-{index}"),
            "base_price": price,
            "base_currency": currency,
            "accepted_currencies": accepted,
            "offers_delivery": True,
            "view_only": False,
            "is_available": True,
            "sort_order": index,
            "popularity": 50,
            "demo_seed": EXPIRED_MARKER,
            "created_at": now,
            "updated_at": now,
        }
        await products_col.insert_one(product_doc)
        inserted += 1

    categories_col = get_catalog_categories_collection()
    for local_category in local_categories:
        count = await products_col.count_documents(
            {"seller_id": seller_id, "category_id": local_category["_id"]},
        )
        await categories_col.update_one(
            {"_id": local_category["_id"]},
            {"$set": {"product_count": count}},
        )

    print(f"  {inserted} productos demo (no deben verse en el marketplace)")
    print()
    print("Credenciales para probar login vencido:")
    print(f"  Tienda: {STORE_NAME}")
    print(f"  Teléfono: {STORE_PHONE}")
    print(f"  Contraseña: {DEMO_PASSWORD}")
    print(f"  Slug público: {store_slug} (debe responder 404 en catálogo)")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed tienda demo con plan vencido")
    parser.add_argument("--wipe", action="store_true", help="Elimina la tienda demo vencida")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin escribir en la BD")
    args = parser.parse_args()

    await connect_to_mongo()
    await ensure_category_seed()
    await ensure_product_category_seed()
    await ensure_catalog_indexes()

    try:
        if args.wipe:
            await wipe_expired_demo()
            if not args.dry_run:
                print("Listo.")
            return

        await seed_expired_store(dry_run=args.dry_run)
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
