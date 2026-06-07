"""
Pobla el catálogo de la tienda «Tienducha» con categorías y productos de demo.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\seed_catalog_tienducha.py
"""

import asyncio
import re
import sys
import uuid
from pathlib import Path

from bson import ObjectId

import httpx

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

STORE_NAME = "Tienducha"
PRODUCTS_UPLOADS_DIR = Path(__file__).resolve().parents[1] / "uploads" / "products"

BUSINESS_CATEGORY_BY_SECTION = {
    "Electrodomésticos": "hogar",
    "Ferretería": "hogar",
    "Despensa": "comida",
}

CATEGORIES = [
    {
        "name": "Electrodomésticos",
        "products": [
            {"name": "Licuadora Oster", "price": 4500, "currency": "CUP", "description": "Jarra de vidrio, 2 velocidades."},
            {"name": "Ventilador recargable", "price": 3200, "currency": "CUP", "description": "Batería de 8 horas, portátil."},
            {"name": "Microondas 20L", "price": 185, "currency": "USD", "accepted_currencies": ["CUP"], "description": "Panel digital, 700W."},
            {"name": "Plancha de ropa", "price": 2800, "currency": "CUP", "is_available": False},
            {"name": "Cafetera italiana", "price": 15, "currency": "USD", "accepted_currencies": ["CUP", "MLC"]},
            {"name": "Batidora manual", "price": 1900, "currency": "CUP"},
        ],
    },
    {
        "name": "Ferretería",
        "products": [
            {"name": "Martillo de carpintero", "price": 850, "currency": "CUP"},
            {"name": "Juego de destornilladores", "price": 1200, "currency": "CUP", "description": "6 piezas, punta imantada."},
            {"name": "Cinta métrica 5 m", "price": 6, "currency": "USD", "accepted_currencies": ["CUP"]},
            {"name": "Pintura blanca 1 galón", "price": 2400, "currency": "CUP", "offers_delivery": False},
            {"name": "Taladro inalámbrico", "price": 95, "currency": "USD", "accepted_currencies": ["CUP", "MLC"]},
            {"name": "Clavos surtidos 1 kg", "price": 450, "currency": "CUP"},
        ],
    },
    {
        "name": "Despensa",
        "products": [
            {"name": "Arroz 1 kg", "price": 180, "currency": "CUP", "view_only": True},
            {"name": "Aceite vegetal 900 ml", "price": 420, "currency": "CUP"},
            {"name": "Frijoles negros 500 g", "price": 95, "currency": "CUP"},
            {"name": "Azúcar 1 kg", "price": 160, "currency": "CUP", "is_available": False},
            {"name": "Café molido 250 g", "price": 8, "currency": "USD", "accepted_currencies": ["CUP"]},
            {"name": "Leche en polvo 400 g", "price": 520, "currency": "CUP", "description": "Bolsa sellada, larga duración."},
        ],
    },
]


def _slug(*parts: str) -> str:
    raw = "-".join(parts).lower()
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")


async def download_image(seller_id: str, slug: str) -> str:
    url = f"https://picsum.photos/seed/{slug}/500/500"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    PRODUCTS_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{seller_id}-{_slug(slug)}-{uuid.uuid4().hex[:6]}.jpg"
    filepath = PRODUCTS_UPLOADS_DIR / filename
    filepath.write_bytes(response.content)
    return f"/uploads/products/{filename}"


async def main() -> None:
    await connect_to_mongo()
    await ensure_catalog_indexes()

    registration = await get_registrations_collection().find_one({"store_name": STORE_NAME})
    if not registration:
        print(f"No se encontró la tienda «{STORE_NAME}».")
        await close_mongo_connection()
        return

    seller_id = str(registration["_id"])
    default_delivery = bool(registration.get("offers_delivery"))

    business_area = {
        "province_id": "la-habana",
        "province_name": "La Habana",
        "municipality_id": "plaza-de-la-revolucion",
        "municipality_name": "Plaza de la Revolución",
    }
    profile_updates: dict = {"business_area": business_area}
    if (
        registration.get("profile_photo_url")
        and registration.get("category_ids")
        and registration.get("offers_delivery") is not None
        and not registration.get("profile_completed_at")
    ):
        profile_updates["profile_completed_at"] = to_utc_naive(utc_now())

    await get_registrations_collection().update_one(
        {"_id": registration["_id"]},
        {"$set": profile_updates},
    )
    print(f"Zona de negocio: {business_area['municipality_name']}, {business_area['province_name']}")

    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    await products_col.delete_many({"seller_id": seller_id})

    now = to_utc_naive(utc_now())
    local_category_ids: dict[str, ObjectId] = {}

    for category_order, category in enumerate(CATEGORIES):
        local_doc = {
            "seller_id": seller_id,
            "name": category["name"],
            "product_count": len(category["products"]),
            "sort_order": category_order,
            "created_at": now,
            "updated_at": now,
        }
        existing_local = await categories_col.find_one(
            {"seller_id": seller_id, "name": category["name"]}
        )
        if existing_local:
            local_category_ids[category["name"]] = existing_local["_id"]
            await categories_col.update_one(
                {"_id": existing_local["_id"]},
                {"$set": {"product_count": len(category["products"]), "updated_at": now}},
            )
        else:
            result = await categories_col.insert_one(local_doc)
            local_category_ids[category["name"]] = result.inserted_id

    for category_order, category in enumerate(CATEGORIES):
        global_category_id = BUSINESS_CATEGORY_BY_SECTION[category["name"]]
        local_category_id = local_category_ids[category["name"]]
        print(f"\n{category['name']} ({len(category['products'])} productos)")

        for product_order, product in enumerate(category["products"]):
            slug = _slug(STORE_NAME, category["name"], product["name"], str(product_order))
            image_url = await download_image(seller_id, slug)

            product_doc = {
                "seller_id": seller_id,
                "category_id": local_category_id,
                "global_category_id": global_category_id,
                "name": product["name"],
                "description": product.get("description"),
                "image_url": image_url,
                "base_price": float(product["price"]),
                "base_currency": product.get("currency", "CUP"),
                "accepted_currencies": list(product.get("accepted_currencies", [])),
                "offers_delivery": bool(product.get("offers_delivery", default_delivery)),
                "view_only": bool(product.get("view_only", False)),
                "is_available": bool(product.get("is_available", True)),
                "sort_order": product_order,
                "created_at": now,
                "updated_at": now,
            }
            await products_col.insert_one(product_doc)
            print(f"  · {product['name']}")

    total_products = sum(len(category["products"]) for category in CATEGORIES)
    print(f"\nListo: {len(CATEGORIES)} categorías y {total_products} productos para «{STORE_NAME}».")
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
