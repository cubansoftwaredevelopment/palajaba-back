import json
import re
import uuid
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status

from app.constants import CURRENCY_CODES, SUPPORTED_CURRENCIES
from app.database import (
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.services.categories import business_category_name, resolve_product_global_category_id
from app.services.product_categories import map_local_category_name_to_business_category
from app.schemas.catalog import (
    CatalogCategoryCreate,
    CatalogCategoryProductSortUpdate,
    CatalogCategoryPublic,
    CatalogCategoryReorder,
    CatalogProductImagePublic,
    CatalogProductPublic,
    CatalogProductReorder,
    CatalogProductSearchPublic,
    CatalogProductSuggestion,
    CatalogSummaryPublic,
    CurrencyPublic,
)
from app.services.catalog_product_sort import (
    DEFAULT_PRODUCT_SORT_MODE,
    normalize_product_sort_mode,
    sort_product_docs,
)
from app.services.media_storage import read_image_upload, remove_image, store_image
from app.utils.datetime import to_utc_naive, utc_now

MAX_CATEGORIES_PER_SELLER = 20
MAX_PRODUCTS_PER_CATEGORY = 100
MAX_PRODUCT_IMAGES = 6
ORDERED_PRODUCT_PREVIEW_LIMIT = 12
ORDERED_PRODUCT_SEARCH_LIMIT = 40


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
    images = public_product_images(doc)
    frontal_url = next((image.image_url for image in images if image.is_frontal), None)
    return CatalogProductPublic(
        id=str(doc["_id"]),
        category_id=str(doc.get("category_id") or ""),
        global_category_id=global_category_id,
        global_category_name=business_category_name(global_category_id),
        name=doc["name"],
        description=doc.get("description"),
        image_url=frontal_url or str(doc.get("image_url") or ""),
        images=images,
        base_price=float(doc["base_price"]),
        base_currency=doc["base_currency"],
        accepted_currencies=list(doc.get("accepted_currencies") or []),
        offers_delivery=bool(doc.get("offers_delivery")),
        view_only=bool(doc.get("view_only")),
        is_available=bool(doc.get("is_available", True)),
        popularity=int(doc.get("popularity") or 0),
        sort_order=int(doc.get("sort_order") or 0),
        stock_quantity=(
            int(doc["stock_quantity"])
            if doc.get("stock_quantity") is not None
            else None
        ),
    )


def document_to_category(doc: dict[str, Any], products: list[CatalogProductPublic] | None = None) -> CatalogCategoryPublic:
    return CatalogCategoryPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        product_count=int(doc.get("product_count") or 0),
        product_sort_mode=normalize_product_sort_mode(doc.get("product_sort_mode")),
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


def parse_ordered_product_ids(raw_ids: list) -> list[ObjectId]:
    parsed: list[ObjectId] = []
    seen: set[ObjectId] = set()
    for raw in raw_ids:
        try:
            product_id = ObjectId(str(raw))
        except (InvalidId, TypeError):
            continue
        if product_id in seen:
            continue
        seen.add(product_id)
        parsed.append(product_id)
    return parsed


def ordered_product_search_limit(query: str) -> int:
    if query.strip():
        return ORDERED_PRODUCT_SEARCH_LIMIT
    return ORDERED_PRODUCT_PREVIEW_LIMIT


def ordered_product_search_filter(
    seller_id: str,
    product_ids: list[ObjectId],
    query: str,
    category_ids: list[ObjectId],
) -> dict[str, Any] | None:
    if not product_ids:
        return None

    product_filter: dict[str, Any] = {
        "seller_id": seller_id,
        "_id": {"$in": product_ids},
        "is_available": True,
        "view_only": {"$ne": True},
    }
    normalized = query.strip()
    if not normalized:
        return product_filter

    regex = {"$regex": re.escape(normalized), "$options": "i"}
    clauses: list[dict[str, Any]] = [{"name": regex}]
    if category_ids:
        clauses.append({"category_id": {"$in": category_ids}})
    product_filter["$or"] = clauses
    return product_filter


async def search_seller_ordered_products(seller_id: str, query: str) -> CatalogProductSearchPublic:
    raw_ids = await get_orders_collection().distinct("items.product_id", {"seller_id": seller_id})
    product_ids = parse_ordered_product_ids(raw_ids)
    if not product_ids:
        return CatalogProductSearchPublic()

    normalized = query.strip()
    category_ids: list[ObjectId] = []
    if normalized:
        category_ids = await get_catalog_categories_collection().distinct(
            "_id",
            {
                "seller_id": seller_id,
                "name": {"$regex": re.escape(normalized), "$options": "i"},
            },
        )

    product_filter = ordered_product_search_filter(seller_id, product_ids, normalized, category_ids)
    products_col = get_catalog_products_collection()
    total = await products_col.count_documents(product_filter)
    limit = ordered_product_search_limit(normalized)
    docs = await products_col.find(product_filter).sort("name", 1).limit(limit).to_list(length=limit)

    category_oids = [doc["category_id"] for doc in docs if doc.get("category_id") is not None]
    category_docs = []
    if category_oids:
        category_docs = await get_catalog_categories_collection().find(
            {"_id": {"$in": category_oids}}
        ).to_list(length=None)
    category_names = {doc["_id"]: doc.get("name") or "" for doc in category_docs}

    suggestions = [
        CatalogProductSuggestion(
            id=str(doc["_id"]),
            name=doc["name"],
            category_name=category_names.get(doc.get("category_id"), ""),
            base_price=float(doc["base_price"]),
            base_currency=doc["base_currency"],
            stock_quantity=(
                int(doc["stock_quantity"]) if doc.get("stock_quantity") is not None else None
            ),
        )
        for doc in docs
    ]
    return CatalogProductSearchPublic(
        products=suggestions,
        total=total,
        has_ordered_products=True,
    )


async def get_catalog_summary(seller_id: str) -> CatalogSummaryPublic:
    categories_col = get_catalog_categories_collection()
    products_col = get_catalog_products_collection()

    category_docs = await categories_col.find({"seller_id": seller_id}).sort("sort_order", 1).to_list(length=None)
    product_docs = await products_col.find({"seller_id": seller_id}).to_list(length=None)

    products_by_category: dict[str, list[dict[str, Any]]] = {}
    for doc in product_docs:
        category_key = str(doc.get("category_id") or "")
        products_by_category.setdefault(category_key, []).append(doc)

    categories: list[CatalogCategoryPublic] = []
    for category_doc in category_docs:
        category_id = str(category_doc["_id"])
        mode = normalize_product_sort_mode(category_doc.get("product_sort_mode"))
        raw_products = sort_product_docs(products_by_category.get(category_id, []), mode)
        products = [document_to_product(doc) for doc in raw_products]
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
        "product_sort_mode": DEFAULT_PRODUCT_SORT_MODE,
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
        from app.services.product_popularity import delete_popularity_events_for_products

        await delete_popularity_events_for_products(
            [str(product_doc["_id"]) for product_doc in product_docs]
        )
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


async def _apply_product_sort_order(
    seller_id: str,
    category_oid: ObjectId,
    ordered_product_ids: list[str],
) -> None:
    products_col = get_catalog_products_collection()
    now = to_utc_naive(utc_now())
    for index, product_id in enumerate(ordered_product_ids):
        try:
            product_oid = ObjectId(product_id)
        except InvalidId as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La lista contiene productos inválidos.",
            ) from exc
        result = await products_col.update_one(
            {
                "_id": product_oid,
                "seller_id": seller_id,
                "category_id": category_oid,
            },
            {"$set": {"sort_order": index, "updated_at": now}},
        )
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La lista contiene productos inválidos o duplicados.",
            )


async def _snapshot_category_product_order(
    seller_id: str,
    category_doc: dict[str, Any],
) -> None:
    products_col = get_catalog_products_collection()
    category_oid = category_doc["_id"]
    mode = normalize_product_sort_mode(category_doc.get("product_sort_mode"))
    product_docs = await products_col.find(
        {"seller_id": seller_id, "category_id": category_oid},
    ).to_list(length=None)
    if not product_docs:
        return
    ordered_ids = [str(doc["_id"]) for doc in sort_product_docs(product_docs, mode)]
    await _apply_product_sort_order(seller_id, category_oid, ordered_ids)


async def update_category_product_sort_mode(
    seller_id: str,
    category_id: str,
    payload: CatalogCategoryProductSortUpdate,
) -> CatalogSummaryPublic:
    category_oid = _parse_category_id(category_id)
    categories_col = get_catalog_categories_collection()
    category_doc = await categories_col.find_one({"_id": category_oid, "seller_id": seller_id})
    if not category_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada.",
        )

    current_mode = normalize_product_sort_mode(category_doc.get("product_sort_mode"))
    next_mode = normalize_product_sort_mode(payload.product_sort_mode)
    now = to_utc_naive(utc_now())

    if next_mode == "manual" and current_mode != "manual":
        await _snapshot_category_product_order(seller_id, category_doc)

    await categories_col.update_one(
        {"_id": category_oid, "seller_id": seller_id},
        {"$set": {"product_sort_mode": next_mode, "updated_at": now}},
    )

    return await get_catalog_summary(seller_id)


async def reorder_catalog_products(
    seller_id: str,
    category_id: str,
    payload: CatalogProductReorder,
) -> CatalogSummaryPublic:
    category_oid = _parse_category_id(category_id)
    categories_col = get_catalog_categories_collection()
    category_doc = await categories_col.find_one({"_id": category_oid, "seller_id": seller_id})
    if not category_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categoría no encontrada.",
        )

    mode = normalize_product_sort_mode(category_doc.get("product_sort_mode"))
    if mode != "manual":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo puedes reordenar productos cuando el modo es manual.",
        )

    products_col = get_catalog_products_collection()
    existing_docs = await products_col.find(
        {"seller_id": seller_id, "category_id": category_oid},
    ).to_list(length=None)
    existing_ids = {str(doc["_id"]) for doc in existing_docs}

    if not existing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta categoría no tiene productos para ordenar.",
        )

    if len(payload.product_ids) != len(existing_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista debe incluir todos los productos de la categoría.",
        )

    if set(payload.product_ids) != existing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista contiene productos inválidos o duplicados.",
        )

    await _apply_product_sort_order(seller_id, category_oid, payload.product_ids)
    return await get_catalog_summary(seller_id)


def product_images_from_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw_images = doc.get("images")
    images: list[dict[str, Any]] = []
    if isinstance(raw_images, list):
        for item in raw_images:
            if not isinstance(item, dict):
                continue
            image_url = str(item.get("image_url") or "").strip()
            image_id = str(item.get("id") or "").strip()
            if not image_url or not image_id:
                continue
            images.append(
                {
                    "id": image_id,
                    "image_url": image_url,
                    "image_public_id": item.get("image_public_id"),
                    "is_frontal": bool(item.get("is_frontal")),
                }
            )
    if images:
        return _with_single_frontal(images)
    image_url = str(doc.get("image_url") or "").strip()
    if not image_url:
        return []
    return [
        {
            "id": "legacy",
            "image_url": image_url,
            "image_public_id": doc.get("image_public_id"),
            "is_frontal": True,
        }
    ]


def public_product_images(doc: dict[str, Any]) -> list[CatalogProductImagePublic]:
    images = product_images_from_document(doc)
    frontal = [image for image in images if image["is_frontal"]]
    rest = [image for image in images if not image["is_frontal"]]
    return [
        CatalogProductImagePublic(
            id=image["id"],
            image_url=image["image_url"],
            is_frontal=image["is_frontal"],
        )
        for image in [*frontal, *rest]
    ]


def _with_single_frontal(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not images:
        return []
    if len(images) == 1:
        images[0]["is_frontal"] = True
        return images
    frontal_indexes = [index for index, image in enumerate(images) if image["is_frontal"]]
    chosen = frontal_indexes[0] if frontal_indexes else 0
    for index, image in enumerate(images):
        image["is_frontal"] = index == chosen
    return images


def _frontal_fields(images: list[dict[str, Any]]) -> dict[str, Any]:
    frontal = next((image for image in images if image["is_frontal"]), images[0])
    return {
        "image_url": frontal["image_url"],
        "image_public_id": frontal.get("image_public_id"),
        "images": images,
    }


def _named_uploads(
    photo: UploadFile | None,
    photos: list[UploadFile] | None,
) -> list[UploadFile]:
    uploads: list[UploadFile] = []
    if photo is not None and photo.filename:
        uploads.append(photo)
    for item in photos or []:
        if item is not None and item.filename:
            uploads.append(item)
    return uploads


def _parse_remove_image_ids(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista de fotos a quitar no es válida.",
        ) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista de fotos a quitar no es válida.",
        )
    return [item.strip() for item in parsed if item.strip()]


async def _delete_stored_images(images: list[dict[str, Any]]) -> None:
    for image in images:
        await _delete_product_image_file(
            image.get("image_url"),
            public_id=image.get("image_public_id"),
        )


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
    photo: UploadFile | None = None,
    photos: list[UploadFile] | None = None,
    frontal_index: int = 0,
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

    uploads = _named_uploads(photo, photos)
    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sube al menos una foto del producto.",
        )
    if len(uploads) > MAX_PRODUCT_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un producto puede tener hasta {MAX_PRODUCT_IMAGES} fotos.",
        )
    if len(uploads) == 1:
        frontal_index = 0
    elif frontal_index < 0 or frontal_index >= len(uploads):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Elige una foto frontal válida.",
        )
    stored_images: list[dict[str, Any]] = []
    for index, upload in enumerate(uploads):
        stored = await _save_product_photo(seller_id, upload)
        stored_images.append(
            {
                "id": uuid.uuid4().hex,
                "image_url": stored.url,
                "image_public_id": stored.public_id,
                "is_frontal": index == frontal_index,
            }
        )
    now = to_utc_naive(utc_now())
    doc = {
        "seller_id": seller_id,
        "category_id": local_category_oid,
        "global_category_id": normalized_global_category_id,
        "name": normalized_name,
        "description": cleaned_description,
        **_frontal_fields(stored_images),
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


def _choose_frontal_image(
    images: list[dict[str, Any]],
    *,
    frontal_image_id: str | None,
    frontal_new_index: int | None,
    new_images: list[dict[str, Any]],
) -> None:
    if len(images) == 1:
        images[0]["is_frontal"] = True
        return
    chosen_id = None
    if frontal_new_index is not None:
        if frontal_new_index < 0 or frontal_new_index >= len(new_images):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Elige una foto frontal válida.",
            )
        chosen_id = new_images[frontal_new_index]["id"]
    elif frontal_image_id:
        chosen_id = frontal_image_id.strip()
    else:
        current = next((image for image in images if image["is_frontal"]), None)
        chosen_id = current["id"] if current else images[0]["id"]
    if not any(image["id"] == chosen_id for image in images):
        chosen_id = next((image["id"] for image in images if image["is_frontal"]), images[0]["id"])
    for image in images:
        image["is_frontal"] = image["id"] == chosen_id


async def _updated_product_images(
    seller_id: str,
    doc: dict[str, Any],
    *,
    photo: UploadFile | None,
    photos: list[UploadFile] | None,
    remove_image_ids_raw: str | None,
    frontal_image_id: str | None,
    frontal_new_index: int | None,
) -> dict[str, Any] | None:
    extra_uploads = _named_uploads(None, photos)
    legacy_photo = photo if photo is not None and photo.filename else None
    remove_ids = _parse_remove_image_ids(remove_image_ids_raw)
    touches_gallery = bool(
        extra_uploads
        or remove_ids
        or (frontal_image_id and frontal_image_id.strip())
        or frontal_new_index is not None
    )
    if legacy_photo is not None and not touches_gallery:
        stored = await _save_product_photo(seller_id, legacy_photo)
        replacement = [
            {
                "id": uuid.uuid4().hex,
                "image_url": stored.url,
                "image_public_id": stored.public_id,
                "is_frontal": True,
            }
        ]
        await _delete_stored_images(product_images_from_document(doc))
        return _frontal_fields(replacement)
    if not touches_gallery:
        return None

    current = product_images_from_document(doc)
    remove_set = set(remove_ids)
    kept = [image for image in current if image["id"] not in remove_set]
    removed = [image for image in current if image["id"] in remove_set]
    uploads = [*([legacy_photo] if legacy_photo is not None else []), *extra_uploads]
    if len(kept) + len(uploads) > MAX_PRODUCT_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un producto puede tener hasta {MAX_PRODUCT_IMAGES} fotos.",
        )
    new_images: list[dict[str, Any]] = []
    for upload in uploads:
        stored = await _save_product_photo(seller_id, upload)
        new_images.append(
            {
                "id": uuid.uuid4().hex,
                "image_url": stored.url,
                "image_public_id": stored.public_id,
                "is_frontal": False,
            }
        )
    combined = [*kept, *new_images]
    if not combined:
        for image in new_images:
            await _delete_product_image_file(
                image.get("image_url"),
                public_id=image.get("image_public_id"),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El producto debe conservar al menos una foto.",
        )
    _choose_frontal_image(
        combined,
        frontal_image_id=frontal_image_id,
        frontal_new_index=frontal_new_index,
        new_images=new_images,
    )
    for image in combined:
        if image["id"] == "legacy":
            image["id"] = uuid.uuid4().hex
    await _delete_stored_images(removed)
    return _frontal_fields(combined)


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
    photos: list[UploadFile] | None = None,
    remove_image_ids_raw: str | None = None,
    frontal_image_id: str | None = None,
    frontal_new_index: int | None = None,
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

    image_fields = await _updated_product_images(
        seller_id,
        doc,
        photo=photo,
        photos=photos,
        remove_image_ids_raw=remove_image_ids_raw,
        frontal_image_id=frontal_image_id,
        frontal_new_index=frontal_new_index,
    )
    if image_fields is not None:
        update_fields.update(image_fields)

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
    from app.services.product_popularity import delete_popularity_events_for_products

    await delete_popularity_events_for_products([str(doc["_id"])])
    await products.delete_one({"_id": doc["_id"]})
    await _delete_stored_images(product_images_from_document(doc))
    category_oid = doc.get("category_id")
    if isinstance(category_oid, ObjectId):
        await _sync_local_category_product_count(seller_id, category_oid)

