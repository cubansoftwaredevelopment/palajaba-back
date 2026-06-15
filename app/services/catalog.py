import json
import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status

from app.constants import CURRENCY_CODES, SUPPORTED_CURRENCIES
from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.services.categories import business_category_name, resolve_product_global_category_id
from app.services.product_categories import map_local_category_name_to_business_category
from app.schemas.catalog import (
    CatalogCategoryCreate,
    CatalogCategoryPublic,
    CatalogCategoryReorder,
    CatalogProductPublic,
    CatalogSummaryPublic,
    CurrencyPublic,
)
from app.services.media_storage import read_image_upload, remove_image, store_image
from app.utils.datetime import to_utc_naive, utc_now

MAX_CATEGORIES_PER_SELLER = 20
MAX_PRODUCTS_PER_CATEGORY = 100


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    if len(cleaned) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de la categoría debe tener al menos 2 caracteres.",
        )
    return cleaned


def _normalize_product_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    if len(cleaned) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del producto debe tener al menos 2 caracteres.",
        )
    if len(cleaned) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del producto no puede superar 120 caracteres.",
        )
    return cleaned


def _parse_category_id(category_id: str) -> ObjectId:
    try:
        return ObjectId(category_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada.",
        ) from exc


def _validate_currency(code: str, field_name: str) -> str:
    normalized = code.strip().upper()
    if normalized not in CURRENCY_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} no es una moneda válida.",
        )
    return normalized


def _parse_accepted_currencies(raw: str, base_currency: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las monedas aceptadas tienen un formato inválido.",
        ) from exc

    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las monedas aceptadas deben ser una lista.",
        )

    accepted: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Las monedas aceptadas deben ser códigos válidos.",
            )
        code = _validate_currency(item, "Una moneda aceptada")
        if code == base_currency:
            continue
        if code not in accepted:
            accepted.append(code)
    return accepted


def document_to_product(doc: dict[str, Any]) -> CatalogProductPublic:
    global_category_id = str(doc.get("global_category_id") or "otros").strip().lower()
    return CatalogProductPublic(
        id=str(doc["_id"]),
        category_id=str(doc.get("category_id") or ""),
        global_category_id=global_category_id,
        global_category_name=business_category_name(global_category_id),
        name=doc["name"],
        description=doc.get("description"),
        image_url=doc["image_url"],
        base_price=float(doc["base_price"]),
        base_currency=doc["base_currency"],
        accepted_currencies=list(doc.get("accepted_currencies") or []),
        offers_delivery=bool(doc.get("offers_delivery")),
        view_only=bool(doc.get("view_only")),
        is_available=bool(doc.get("is_available", True)),
    )


def document_to_category(doc: dict[str, Any], products: list[CatalogProductPublic] | None = None) -> CatalogCategoryPublic:
    return CatalogCategoryPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        product_count=int(doc.get("product_count") or 0),
        products=products or [],
    )


def get_supported_currencies() -> list[CurrencyPublic]:
    return [CurrencyPublic(**item) for item in SUPPORTED_CURRENCIES]


async def _renormalize_category_sort_orders(seller_id: str) -> None:
    collection = get_catalog_categories_collection()
    docs = await collection.find({"seller_id": seller_id}).sort(
        [("sort_order", 1), ("created_at", 1)]
    ).to_list(length=None)
    now = to_utc_naive(utc_now())
    for index, doc in enumerate(docs):
        if doc.get("sort_order") != index:
            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"sort_order": index, "updated_at": now}},
            )


async def _backfill_category_sort_orders() -> None:
    categories = get_catalog_categories_collection()
    seller_ids = await categories.distinct("seller_id")
    for seller_id in seller_ids:
        if seller_id:
            await _renormalize_category_sort_orders(seller_id)


async def ensure_catalog_indexes() -> None:
    categories = get_catalog_categories_collection()
    products = get_catalog_products_collection()
    await categories.create_index([("seller_id", 1), ("name", 1)], unique=True)
    await categories.create_index([("seller_id", 1), ("sort_order", 1)])
    await products.create_index([("seller_id", 1), ("category_id", 1), ("sort_order", 1)])
    await products.create_index([("seller_id", 1), ("global_category_id", 1), ("sort_order", 1)])
    await _backfill_category_sort_orders()
    await _backfill_product_categories()

    from app.services.product_popularity import ensure_popularity_field

    await ensure_popularity_field()


async def _backfill_product_categories() -> None:
    products_col = get_catalog_products_collection()
    categories_col = get_catalog_categories_collection()
    registrations_col = get_registrations_collection()

    cursor = products_col.find({"global_category_id": {"$exists": False}})
    async for product in cursor:
        global_category_id = "otros"
        category_oid = product.get("category_id")
        if isinstance(category_oid, ObjectId):
            seller_category = await categories_col.find_one({"_id": category_oid})
            global_category_id = map_local_category_name_to_business_category(
                seller_category.get("name") if seller_category else None
            )
        await products_col.update_one(
            {"_id": product["_id"]},
            {"$set": {"global_category_id": global_category_id}},
        )

    cursor = products_col.find({"category_id": {"$exists": False}})
    async for product in cursor:
        seller_id = product.get("seller_id")
        if not seller_id:
            continue
        local_category = await categories_col.find_one({"seller_id": seller_id})
        if not local_category:
            continue
        await products_col.update_one(
            {"_id": product["_id"]},
            {"$set": {"category_id": local_category["_id"]}},
        )

    category_docs = await categories_col.find({}).to_list(length=None)
    for category_doc in category_docs:
        seller_id = category_doc.get("seller_id")
        category_oid = category_doc.get("_id")
        if not seller_id or not category_oid:
            continue
        count = await products_col.count_documents(
            {"seller_id": seller_id, "category_id": category_oid}
        )
        await categories_col.update_one(
            {"_id": category_oid},
            {"$set": {"product_count": count}},
        )


async def _get_seller_category_ids(seller_id: str) -> list[str]:
    try:
        seller_oid = ObjectId(seller_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        ) from exc

    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        )
    return list(seller.get("category_ids") or [])


async def _validate_global_category_for_seller(seller_id: str, global_category_id: str) -> str:
    allowed = await _get_seller_category_ids(seller_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completa las categorías de tu negocio en el perfil antes de publicar productos.",
        )
    try:
        return resolve_product_global_category_id(allowed, global_category_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


async def _validate_local_category_id(seller_id: str, category_id: str) -> ObjectId:
    oid = _parse_category_id(category_id)
    collection = get_catalog_categories_collection()
    doc = await collection.find_one({"_id": oid, "seller_id": seller_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selecciona una categoría local válida de tu catálogo.",
        )
    return oid


async def _sync_local_category_product_count(seller_id: str, category_oid: ObjectId) -> None:
    products_col = get_catalog_products_collection()
    categories_col = get_catalog_categories_collection()
    count = await products_col.count_documents(
        {"seller_id": seller_id, "category_id": category_oid}
    )
    await categories_col.update_one(
        {"_id": category_oid, "seller_id": seller_id},
        {"$set": {"product_count": count}},
    )


async def get_catalog_summary(seller_id: str) -> CatalogSummaryPublic:
    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    category_docs = await categories_col.find({"seller_id": seller_id}).sort("sort_order", 1).to_list(length=None)
    product_docs = await products_col.find({"seller_id": seller_id}).sort("sort_order", 1).to_list(length=None)

    products_by_category: dict[str, list[CatalogProductPublic]] = {}
    for doc in product_docs:
        category_key = str(doc.get("category_id") or "")
        products_by_category.setdefault(category_key, []).append(document_to_product(doc))

    categories: list[CatalogCategoryPublic] = []
    for category_doc in category_docs:
        category_id = str(category_doc["_id"])
        products = products_by_category.get(category_id, [])
        categories.append(
            document_to_category(
                {**category_doc, "product_count": len(products)},
                products=products,
            )
        )

    return CatalogSummaryPublic(categories=categories, total_products=len(product_docs))


async def create_catalog_category(seller_id: str, payload: CatalogCategoryCreate) -> CatalogCategoryPublic:
    name = _normalize_name(payload.name)
    collection = get_catalog_categories_collection()

    existing_count = await collection.count_documents({"seller_id": seller_id})
    if existing_count >= MAX_CATEGORIES_PER_SELLER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No puedes crear más de {MAX_CATEGORIES_PER_SELLER} categorías.",
        )

    duplicate = await collection.find_one({"seller_id": seller_id, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya tienes una categoría con ese nombre.",
        )

    now = to_utc_naive(utc_now())
    doc = {
        "seller_id": seller_id,
        "name": name,
        "product_count": 0,
        "sort_order": existing_count,
        "created_at": now,
        "updated_at": now,
    }
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return document_to_category(doc)


async def delete_catalog_category(seller_id: str, category_id: str) -> None:
    oid = _parse_category_id(category_id)
    categories_col = get_catalog_categories_collection()
    doc = await categories_col.find_one({"_id": oid, "seller_id": seller_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada.",
        )

    products_col = get_catalog_products_collection()
    product_docs = await products_col.find(
        {"seller_id": seller_id, "category_id": oid},
    ).to_list(length=None)

    for product_doc in product_docs:
        await _delete_product_image_file(
            product_doc.get("image_url"),
            public_id=product_doc.get("image_public_id"),
        )

    if product_docs:
        await products_col.delete_many({"seller_id": seller_id, "category_id": oid})

    await categories_col.delete_one({"_id": oid})
    await _renormalize_category_sort_orders(seller_id)


async def reorder_catalog_categories(
    seller_id: str,
    payload: CatalogCategoryReorder,
) -> CatalogSummaryPublic:
    collection = get_catalog_categories_collection()
    existing_docs = await collection.find({"seller_id": seller_id}).to_list(length=None)
    existing_ids = {str(doc["_id"]) for doc in existing_docs}

    if not existing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aún no tienes categorías para ordenar.",
        )

    if len(payload.category_ids) != len(existing_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista debe incluir todas tus categorías.",
        )

    if set(payload.category_ids) != existing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista contiene categorías inválidas o duplicadas.",
        )

    now = to_utc_naive(utc_now())
    for index, category_id in enumerate(payload.category_ids):
        category_oid = _parse_category_id(category_id)
        await collection.update_one(
            {"_id": category_oid, "seller_id": seller_id},
            {"$set": {"sort_order": index, "updated_at": now}},
        )

    return await get_catalog_summary(seller_id)


async def _save_product_photo(seller_id: str, file: UploadFile):
    content, content_type = await read_image_upload(file)
    return await store_image(
        content,
        content_type,
        scope="products",
        owner_id=seller_id,
    )


async def create_catalog_product(
    seller_id: str,
    *,
    name: str,
    description: str | None,
    base_price: float,
    base_currency: str,
    accepted_currencies_raw: str,
    category_id: str,
    global_category_id: str,
    offers_delivery: bool,
    view_only: bool,
    is_available: bool,
    photo: UploadFile,
) -> CatalogProductPublic:
    local_category_oid = await _validate_local_category_id(seller_id, category_id)
    normalized_global_category_id = await _validate_global_category_for_seller(
        seller_id,
        global_category_id,
    )
    products = get_catalog_products_collection()
    product_count = await products.count_documents(
        {"seller_id": seller_id, "category_id": local_category_oid}
    )
    if product_count >= MAX_PRODUCTS_PER_CATEGORY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No puedes agregar más de {MAX_PRODUCTS_PER_CATEGORY} productos en una categoría.",
        )

    normalized_name = _normalize_product_name(name)
    normalized_currency = _validate_currency(base_currency, "La moneda base")
    accepted_currencies = _parse_accepted_currencies(accepted_currencies_raw, normalized_currency)

    if base_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El precio base debe ser mayor que cero.",
        )
    if base_price > 999_999_999:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El precio base es demasiado alto.",
        )

    cleaned_description = None
    if description:
        cleaned_description = description.strip() or None
        if cleaned_description and len(cleaned_description) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La descripción no puede superar 500 caracteres.",
            )

    stored_image = await _save_product_photo(seller_id, photo)
    now = to_utc_naive(utc_now())
    doc = {
        "seller_id": seller_id,
        "category_id": local_category_oid,
        "global_category_id": normalized_global_category_id,
        "name": normalized_name,
        "description": cleaned_description,
        "image_url": stored_image.url,
        "image_public_id": stored_image.public_id,
        "base_price": float(base_price),
        "base_currency": normalized_currency,
        "accepted_currencies": accepted_currencies,
        "offers_delivery": bool(offers_delivery),
        "view_only": bool(view_only),
        "is_available": bool(is_available),
        "sort_order": product_count,
        "popularity": 0,
        "created_at": now,
        "updated_at": now,
    }
    result = await products.insert_one(doc)
    doc["_id"] = result.inserted_id
    await _sync_local_category_product_count(seller_id, local_category_oid)

    return document_to_product(doc)


async def _delete_product_image_file(
    image_url: str | None,
    *,
    public_id: str | None = None,
) -> None:
    await remove_image(image_url, public_id=public_id)


async def _get_product_doc(seller_id: str, product_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(product_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        ) from exc

    collection = get_catalog_products_collection()
    doc = await collection.find_one({"_id": oid, "seller_id": seller_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        )
    return doc


def _validate_product_payload(
    *,
    name: str,
    description: str | None,
    base_price: float,
    base_currency: str,
    accepted_currencies_raw: str,
) -> tuple[str, str | None, float, str, list[str]]:
    normalized_name = _normalize_product_name(name)
    normalized_currency = _validate_currency(base_currency, "La moneda base")
    accepted_currencies = _parse_accepted_currencies(accepted_currencies_raw, normalized_currency)

    if base_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El precio base debe ser mayor que cero.",
        )
    if base_price > 999_999_999:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El precio base es demasiado alto.",
        )

    cleaned_description = None
    if description:
        cleaned_description = description.strip() or None
        if cleaned_description and len(cleaned_description) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La descripción no puede superar 500 caracteres.",
            )

    return normalized_name, cleaned_description, float(base_price), normalized_currency, accepted_currencies


async def update_catalog_product(
    seller_id: str,
    product_id: str,
    *,
    name: str,
    description: str | None,
    base_price: float,
    base_currency: str,
    accepted_currencies_raw: str,
    category_id: str,
    global_category_id: str,
    offers_delivery: bool,
    view_only: bool,
    is_available: bool,
    photo: UploadFile | None = None,
) -> CatalogProductPublic:
    doc = await _get_product_doc(seller_id, product_id)
    local_category_oid = await _validate_local_category_id(seller_id, category_id)
    normalized_global_category_id = await _validate_global_category_for_seller(
        seller_id,
        global_category_id,
    )
    previous_category_oid = doc.get("category_id")

    normalized_name, cleaned_description, price, normalized_currency, accepted_currencies = _validate_product_payload(
        name=name,
        description=description,
        base_price=base_price,
        base_currency=base_currency,
        accepted_currencies_raw=accepted_currencies_raw,
    )

    now = to_utc_naive(utc_now())
    update_fields: dict[str, Any] = {
        "name": normalized_name,
        "description": cleaned_description,
        "base_price": price,
        "base_currency": normalized_currency,
        "accepted_currencies": accepted_currencies,
        "category_id": local_category_oid,
        "global_category_id": normalized_global_category_id,
        "offers_delivery": bool(offers_delivery),
        "view_only": bool(view_only),
        "is_available": bool(is_available),
        "updated_at": now,
    }

    if photo is not None and photo.filename:
        stored_image = await _save_product_photo(seller_id, photo)
        await _delete_product_image_file(
            doc.get("image_url"),
            public_id=doc.get("image_public_id"),
        )
        update_fields["image_url"] = stored_image.url
        update_fields["image_public_id"] = stored_image.public_id

    products = get_catalog_products_collection()
    await products.update_one({"_id": doc["_id"]}, {"$set": update_fields})
    await _sync_local_category_product_count(seller_id, local_category_oid)
    if isinstance(previous_category_oid, ObjectId) and previous_category_oid != local_category_oid:
        await _sync_local_category_product_count(seller_id, previous_category_oid)
    updated = await products.find_one({"_id": doc["_id"]})
    return document_to_product(updated)


async def delete_catalog_product(seller_id: str, product_id: str) -> None:
    doc = await _get_product_doc(seller_id, product_id)
    products = get_catalog_products_collection()
    await products.delete_one({"_id": doc["_id"]})
    await _delete_product_image_file(
        doc.get("image_url"),
        public_id=doc.get("image_public_id"),
    )
    category_oid = doc.get("category_id")
    if isinstance(category_oid, ObjectId):
        await _sync_local_category_product_count(seller_id, category_oid)

