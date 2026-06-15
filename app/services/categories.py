from typing import Any

from app.database import get_categories_collection
from app.schemas.seller_profile import CategoryPublic

BUSINESS_CATEGORY_SORT_ORDER = {
    "comida": 1,
    "moda": 2,
    "belleza": 3,
    "hogar": 4,
    "tecnologia": 5,
    "salud": 6,
    "artesanias": 7,
    "servicios": 8,
    "otros": 99,
}

DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"id": "comida", "name": "Comida y bebidas"},
    {"id": "restaurant", "name": "Restaurant y cafeteria"},
    {"id": "energia", "name": "Paneles, EcoFlow y fuentes de energia"},
    {"id": "inmobiliaria", "name": "Inmobiliaria"},
    {"id": "moda", "name": "Moda y accesorios"},
    {"id": "belleza", "name": "Belleza y cuidado personal"},
    {"id": "hogar", "name": "Hogar y decoración"},
    {"id": "tecnologia", "name": "Tecnología"},
    {"id": "salud", "name": "Salud y bienestar"},
    {"id": "artesanias", "name": "Artesanías"},
    {"id": "insumos-fiestas", "name": "Insumos para fiestas"},
    {"id": "construccion", "name": "Materiales y herramientas de construcción"},
    {"id": "articulos-adultos", "name": "Articulos +18"},
    {"id": "servicios", "name": "Servicios"},
    {"id": "otros", "name": "Otros"},
]


def document_to_category(doc: dict[str, Any]) -> CategoryPublic:
    return CategoryPublic(id=doc["id"], name=doc["name"])


def business_category_name(category_id: str) -> str:
    for item in DEFAULT_CATEGORIES:
        if item["id"] == category_id:
            return item["name"]
    return "Otros"


def business_category_sort_order(category_id: str) -> int:
    return BUSINESS_CATEGORY_SORT_ORDER.get(category_id, 99)


async def ensure_category_seed() -> None:
    collection = get_categories_collection()
    await collection.create_index("id", unique=True)
    for category in DEFAULT_CATEGORIES:
        await collection.update_one(
            {"id": category["id"]},
            {"$setOnInsert": category},
            upsert=True,
        )


async def list_categories() -> list[CategoryPublic]:
    collection = get_categories_collection()
    cursor = collection.find({}).sort("name", 1)
    documents = await cursor.to_list(length=100)
    return [document_to_category(doc) for doc in documents]


async def validate_category_ids(category_ids: list[str]) -> None:
    from fastapi import HTTPException, status

    collection = get_categories_collection()
    count = await collection.count_documents({"id": {"$in": category_ids}})
    if count != len(category_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Una o más categorías no son válidas.",
        )
