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
    "construccion": 8,
    "servicios": 9,
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

_BUSINESS_CATEGORY_BY_ID = {item["id"]: item["name"] for item in DEFAULT_CATEGORIES}

# IDs legacy o de backfills antiguos → id canónico de DEFAULT_CATEGORIES.
CATEGORY_ID_ALIASES: dict[str, str] = {
    "ferreteria": "construccion",
    "ferretería": "construccion",
    "construccion-herramientas": "construccion",
    "construcción-herramientas": "construccion",
    "alimentos": "comida",
    "ropa-zapato-accesorios": "moda",
    "muebles-decoracion": "hogar",
    "muebles-decoración": "hogar",
    "computadoras-celulares": "tecnologia",
    "electronica": "tecnologia",
    "electrónica": "tecnologia",
    "electrodomesticos": "hogar",
    "electrodomésticos": "hogar",
    "salud-belleza": "belleza",
    "arte-antiguedades": "artesanias",
    "arte-antigüedades": "artesanias",
}


def document_to_category(doc: dict[str, Any]) -> CategoryPublic:
    return CategoryPublic(id=doc["id"], name=doc["name"])


def normalize_business_category_id(category_id: str | None) -> str:
    normalized = (category_id or "otros").strip().lower()
    if normalized in _BUSINESS_CATEGORY_BY_ID:
        return normalized
    return CATEGORY_ID_ALIASES.get(normalized, "otros")


def business_category_source_ids(category_id: str) -> list[str]:
    canonical = normalize_business_category_id(category_id)
    source_ids = [canonical]
    for alias, target in CATEGORY_ID_ALIASES.items():
        if target == canonical and alias not in source_ids:
            source_ids.append(alias)
    return source_ids


def business_category_name(category_id: str) -> str:
    canonical = normalize_business_category_id(category_id)
    return _BUSINESS_CATEGORY_BY_ID.get(canonical, "Otros")


def business_category_sort_order(category_id: str) -> int:
    canonical = normalize_business_category_id(category_id)
    return BUSINESS_CATEGORY_SORT_ORDER.get(canonical, 99)


async def ensure_category_seed() -> None:
    collection = get_categories_collection()
    await collection.create_index("id", unique=True)
    for category in DEFAULT_CATEGORIES:
        await collection.update_one(
            {"id": category["id"]},
            {"$set": category},
            upsert=True,
        )


async def list_categories() -> list[CategoryPublic]:
    return [
        CategoryPublic(id=item["id"], name=item["name"])
        for item in sorted(DEFAULT_CATEGORIES, key=lambda entry: entry["name"].lower())
    ]


async def validate_category_ids(category_ids: list[str]) -> None:
    from fastapi import HTTPException, status

    known_ids = {item["id"] for item in DEFAULT_CATEGORIES}
    invalid = [category_id for category_id in category_ids if category_id not in known_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Una o más categorías no son válidas.",
        )
