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

_LOCAL_NAME_TO_BUSINESS_CATEGORY = {
    "ferreteria": "construccion",
    "ferretería": "construccion",
    "construccion": "construccion",
    "construcción": "construccion",
    "herramientas": "construccion",
    "materiales y herramientas de construcción": "construccion",
    "materiales y herramientas de construccion": "construccion",
    "despensa": "comida",
    "alimentos": "comida",
    "comida": "comida",
    "restaurant": "restaurant",
    "restaurante": "restaurant",
    "cafeteria": "restaurant",
    "cafetería": "restaurant",
    "ropa": "moda",
    "moda": "moda",
    "muebles": "hogar",
    "decoracion": "hogar",
    "decoración": "hogar",
    "hogar": "hogar",
    "tecnologia": "tecnologia",
    "tecnología": "tecnologia",
    "celulares": "tecnologia",
    "computadoras": "tecnologia",
    "electrodomesticos": "hogar",
    "electrodomésticos": "hogar",
    "electronica": "tecnologia",
    "electrónica": "tecnologia",
    "belleza": "belleza",
    "salud": "salud",
    "artesania": "artesanias",
    "artesanía": "artesanias",
    "artesanias": "artesanias",
    "artesanías": "artesanias",
    "vehiculos": "medios-transporte",
    "vehículos": "medios-transporte",
    "vehiculos-repuestos": "medios-transporte",
    "transporte": "medios-transporte",
    "medios de transporte": "medios-transporte",
    "medios-transporte": "medios-transporte",
    "autos": "medios-transporte",
    "motos": "medios-transporte",
    "servicios": "servicios",
    "otros": "otros",
}


def map_local_category_name_to_business_category(name: str | None) -> str:
    if not name:
        return "otros"
    normalized = name.strip().lower()
    return _LOCAL_NAME_TO_BUSINESS_CATEGORY.get(normalized, "otros")


def map_seller_category_name(name: str | None) -> str:
    """Compatibilidad con scripts antiguos."""
    return map_local_category_name_to_business_category(name)


def document_to_category(doc: dict[str, Any]) -> CategoryPublic:
    return CategoryPublic(id=doc["id"], name=doc["name"])


def category_name(category_id: str) -> str:
    return _CATEGORY_BY_ID.get(category_id, {}).get("name", "Otros")


def category_sort_order(category_id: str) -> int:
    return int(_CATEGORY_BY_ID.get(category_id, {}).get("sort_order", 99))


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
