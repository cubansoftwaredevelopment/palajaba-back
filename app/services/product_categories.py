"""Categorías globales de productos, inspiradas en Revolico (Compra / Venta)."""

from typing import Any

from fastapi import HTTPException, status

from app.database import get_product_categories_collection
from app.schemas.seller_profile import CategoryPublic

# Taxonomía principal de Revolico para artículos de compra/venta.
REVOLICO_PRODUCT_CATEGORIES: list[dict[str, Any]] = [
    {"id": "electrodomesticos", "name": "Electrodomésticos", "sort_order": 1},
    {"id": "electronica", "name": "Electrónica", "sort_order": 2},
    {"id": "computadoras-celulares", "name": "Computadoras y Celulares", "sort_order": 3},
    {"id": "ropa-zapato-accesorios", "name": "Ropa, Zapato y Accesorios", "sort_order": 4},
    {"id": "muebles-decoracion", "name": "Muebles y Decoración", "sort_order": 5},
    {"id": "construccion-herramientas", "name": "Construcción y Herramientas", "sort_order": 6},
    {"id": "alimentos", "name": "Alimentos", "sort_order": 7},
    {"id": "salud-belleza", "name": "Salud y Belleza", "sort_order": 8},
    {"id": "deportes-recreacion", "name": "Deportes y Recreación", "sort_order": 9},
    {"id": "mascotas", "name": "Mascotas", "sort_order": 10},
    {"id": "bebes-ninos", "name": "Bebés y Niños", "sort_order": 11},
    {"id": "juguetes", "name": "Juguetes", "sort_order": 12},
    {"id": "arte-antiguedades", "name": "Arte y Antigüedades", "sort_order": 13},
    {"id": "jardin-agricultura", "name": "Jardín y Agricultura", "sort_order": 14},
    {"id": "libros-musica", "name": "Libros y Música", "sort_order": 15},
    {"id": "vehiculos-repuestos", "name": "Vehículos y Repuestos", "sort_order": 16},
    {"id": "otros", "name": "Otros", "sort_order": 99},
]

_CATEGORY_BY_ID = {item["id"]: item for item in REVOLICO_PRODUCT_CATEGORIES}

# IDs de categorías de negocio (perfil del vendedor) → taxonomía del marketplace.
BUSINESS_TO_PRODUCT_CATEGORY_MAP: dict[str, str] = {
    "comida": "alimentos",
    "restaurant": "alimentos",
    "energia": "electrodomesticos",
    "inmobiliaria": "otros",
    "moda": "ropa-zapato-accesorios",
    "belleza": "salud-belleza",
    "hogar": "muebles-decoracion",
    "tecnologia": "computadoras-celulares",
    "salud": "salud-belleza",
    "artesanias": "arte-antiguedades",
    "insumos-fiestas": "otros",
    "construccion": "construccion-herramientas",
    "articulos-adultos": "otros",
    "servicios": "otros",
    "otros": "otros",
}

_SELLER_CATEGORY_NAME_MAP = {
    "electrodomesticos": "electrodomesticos",
    "electrodomésticos": "electrodomesticos",
    "electronica": "electronica",
    "electrónica": "electronica",
    "ferreteria": "construccion-herramientas",
    "ferretería": "construccion-herramientas",
    "construccion": "construccion-herramientas",
    "construcción": "construccion-herramientas",
    "herramientas": "construccion-herramientas",
    "despensa": "alimentos",
    "alimentos": "alimentos",
    "comida": "alimentos",
    "ropa": "ropa-zapato-accesorios",
    "moda": "ropa-zapato-accesorios",
    "muebles": "muebles-decoracion",
    "decoracion": "muebles-decoracion",
    "decoración": "muebles-decoracion",
    "tecnologia": "computadoras-celulares",
    "tecnología": "computadoras-celulares",
    "celulares": "computadoras-celulares",
    "computadoras": "computadoras-celulares",
    "belleza": "salud-belleza",
    "salud": "salud-belleza",
    "deportes": "deportes-recreacion",
    "mascotas": "mascotas",
    "juguetes": "juguetes",
    "libros": "libros-musica",
    "musica": "libros-musica",
    "música": "libros-musica",
    "vehiculos": "vehiculos-repuestos",
    "vehículos": "vehiculos-repuestos",
    "repuestos": "vehiculos-repuestos",
    "otros": "otros",
}


def document_to_category(doc: dict[str, Any]) -> CategoryPublic:
    return CategoryPublic(id=doc["id"], name=doc["name"])


def category_name(category_id: str) -> str:
    return _CATEGORY_BY_ID.get(category_id, {}).get("name", "Otros")


def category_sort_order(category_id: str) -> int:
    return int(_CATEGORY_BY_ID.get(category_id, {}).get("sort_order", 99))


def resolve_marketplace_category_id(category_id: str | None) -> str:
    normalized = (category_id or "otros").strip().lower()
    if normalized in _CATEGORY_BY_ID:
        return normalized
    return BUSINESS_TO_PRODUCT_CATEGORY_MAP.get(normalized, "otros")


def marketplace_category_source_ids(category_id: str) -> list[str]:
    resolved = resolve_marketplace_category_id(category_id)
    source_ids = [resolved]
    for business_id, product_id in BUSINESS_TO_PRODUCT_CATEGORY_MAP.items():
        if product_id == resolved and business_id not in source_ids:
            source_ids.append(business_id)
    return source_ids


def map_seller_category_name(name: str | None) -> str:
    if not name:
        return "otros"
    normalized = name.strip().lower()
    return _SELLER_CATEGORY_NAME_MAP.get(normalized, "otros")


async def ensure_product_category_seed() -> None:
    collection = get_product_categories_collection()
    await collection.create_index("id", unique=True)
    for category in REVOLICO_PRODUCT_CATEGORIES:
        await collection.update_one(
            {"id": category["id"]},
            {"$set": category},
            upsert=True,
        )


async def list_product_categories() -> list[CategoryPublic]:
    collection = get_product_categories_collection()
    cursor = collection.find({}).sort("sort_order", 1)
    documents = await cursor.to_list(length=200)
    return [document_to_category(doc) for doc in documents]


async def validate_product_category_id(category_id: str) -> str:
    normalized = category_id.strip().lower()
    if normalized not in _CATEGORY_BY_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La categoría del producto no es válida.",
        )
    return normalized
