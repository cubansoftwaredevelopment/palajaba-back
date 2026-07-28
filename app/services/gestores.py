from __future__ import annotations

import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pydantic import ValidationError
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.database import (
    get_catalog_products_collection,
    get_gestores_collection,
    get_registrations_collection,
)
from app.schemas.gestores import (
    GestorAllowedProductPublic,
    GestorCatalogAccess,
    GestorCatalogAccessUpdate,
    GestorCheckoutPhones,
    GestorCheckoutPhonesUpdate,
    GestorDeleteResult,
    GestorLoginRequiresSetup,
    GestorLoginResponse,
    GestorPublic,
    GestorSelectedProduct,
    GestorSelectedProductsUpdate,
)
from app.schemas.marketplace import MarketplaceCheckoutPhonePublic
from app.security import (
    create_gestor_setup_token,
    create_gestor_token,
    decode_gestor_setup_token,
    hash_password,
    verify_password,
)
from app.services.plans import max_gestores_for_plan, seller_can_add_gestor
from app.services.subscriptions import is_subscription_active
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.phone import phone_display
from app.utils.store_slug import store_name_to_slug

_USERNAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")


def normalize_gestor_username(value: str) -> str:
    return value.strip().lower()


def validate_gestor_username(value: str) -> str:
    normalized = normalize_gestor_username(value)
    if len(normalized) < 2 or len(normalized) > 32:
        raise ValueError("El usuario debe tener entre 2 y 32 caracteres.")
    if not _USERNAME_PATTERN.match(normalized):
        raise ValueError(
            "El usuario solo puede contener letras minúsculas, números, guiones y guiones bajos "
            "(sin empezar ni terminar con guion)."
        )
    return normalized


def default_gestor_catalog_access() -> GestorCatalogAccess:
    return GestorCatalogAccess(mode="selected", product_ids=[])


def parse_gestor_catalog_access(raw: Any) -> GestorCatalogAccess:
    if not isinstance(raw, dict):
        return default_gestor_catalog_access()
    mode = raw.get("mode") or "selected"
    if mode not in ("all", "selected"):
        mode = "selected"
    product_ids = raw.get("product_ids") or []
    if not isinstance(product_ids, list):
        product_ids = []
    return GestorCatalogAccess(mode=mode, product_ids=[str(item) for item in product_ids])


def gestor_catalog_access_to_document(access: GestorCatalogAccess) -> dict[str, Any]:
    return {
        "mode": access.mode,
        "product_ids": list(access.product_ids) if access.mode == "selected" else [],
    }


def product_is_allowed_for_gestores(access: GestorCatalogAccess, product_id: str) -> bool:
    if access.mode == "all":
        return True
    return product_id in set(access.product_ids)


def compute_gestor_display_price(base_price: float, margin_amount: float) -> float:
    """Precio público = precio base del negocio + margen del gestor (misma moneda)."""
    base = max(0.0, float(base_price))
    margin = max(0.0, float(margin_amount))
    return round(base + margin, 2)


def parse_selected_products(raw: Any) -> list[GestorSelectedProduct]:
    if not isinstance(raw, list):
        return []
    products: list[GestorSelectedProduct] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        try:
            margin = float(item.get("margin_amount", 0))
        except (TypeError, ValueError):
            margin = 0.0
        if margin < 0:
            margin = 0.0
        seen.add(product_id)
        products.append(GestorSelectedProduct(product_id=product_id, margin_amount=margin))
    return products


def selected_products_to_document(products: list[GestorSelectedProduct]) -> list[dict[str, Any]]:
    return [
        {"product_id": item.product_id, "margin_amount": float(item.margin_amount)}
        for item in products
    ]


def build_gestor_document(*, seller_id: ObjectId | str, username: str) -> dict[str, Any]:
    now = to_utc_naive(utc_now())
    normalized = validate_gestor_username(username)
    seller_oid = seller_id if isinstance(seller_id, ObjectId) else ObjectId(str(seller_id))
    return {
        "seller_id": seller_oid,
        "username": normalized,
        "password_hash": None,
        "phone": None,
        "selected_products": [],
        "created_at": now,
        "updated_at": now,
    }


def document_to_gestor_public(doc: dict[str, Any]) -> GestorPublic:
    phone_digits = doc.get("phone")
    return GestorPublic(
        id=str(doc["_id"]),
        seller_id=str(doc["seller_id"]),
        username=doc["username"],
        phone=phone_display(phone_digits) if phone_digits else None,
        has_password=bool(doc.get("password_hash")),
        selected_products=parse_selected_products(doc.get("selected_products")),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def ensure_gestor_indexes() -> None:
    collection = get_gestores_collection()
    await collection.create_index(
        [("seller_id", ASCENDING), ("username", ASCENDING)],
        unique=True,
        name="seller_username_unique",
    )
    await collection.create_index([("seller_id", ASCENDING)], name="seller_id_idx")


def default_checkout_gestor_ids() -> list[str]:
    return []


def default_checkout_include_store_phone() -> bool:
    return True


def parse_checkout_gestor_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return default_checkout_gestor_ids()
    return GestorCheckoutPhones(
        gestor_ids=[str(item) for item in raw],
        include_store_phone=True,
    ).gestor_ids


def parse_checkout_include_store_phone(raw: Any) -> bool:
    if raw is None:
        return default_checkout_include_store_phone()
    return bool(raw)


async def ensure_seller_gestor_catalog_defaults() -> None:
    """Backfill de la config de red de gestores en negocios existentes."""
    collection = get_registrations_collection()
    await collection.update_many(
        {"gestor_catalog_access": {"$exists": False}},
        {
            "$set": {
                "gestor_catalog_access": gestor_catalog_access_to_document(
                    default_gestor_catalog_access()
                )
            }
        },
    )
    await collection.update_many(
        {"gestores_enabled": {"$exists": False}},
        {"$set": {"gestores_enabled": False}},
    )
    await collection.update_many(
        {"checkout_gestor_ids": {"$exists": False}},
        {"$set": {"checkout_gestor_ids": default_checkout_gestor_ids()}},
    )
    await collection.update_many(
        {"checkout_include_store_phone": {"$exists": False}},
        {"$set": {"checkout_include_store_phone": default_checkout_include_store_phone()}},
    )


def seller_has_gestores_enabled(seller: dict[str, Any]) -> bool:
    return bool(seller.get("gestores_enabled"))


async def require_seller_gestores_enabled(seller_id: str) -> dict[str, Any]:
    seller = await _get_seller_doc(seller_id)
    if not seller_has_gestores_enabled(seller):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Activa los gestores de venta en la configuración de tu perfil.",
        )
    return seller


async def insert_gestor_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Inserta un gestor; levanta DuplicateKeyError si (seller_id, username) ya existe."""
    collection = get_gestores_collection()
    try:
        result = await collection.insert_one(doc)
    except DuplicateKeyError:
        raise
    created = await collection.find_one({"_id": result.inserted_id})
    if created is None:
        raise RuntimeError("No se pudo leer el gestor recién creado.")
    return created


def _seller_oid(seller_id: str) -> ObjectId:
    try:
        return ObjectId(str(seller_id).strip())
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Negocio no válido.",
        ) from exc


async def _get_seller_doc(seller_id: str) -> dict[str, Any]:
    doc = await get_registrations_collection().find_one({"_id": _seller_oid(seller_id)})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Negocio no encontrado.")
    return doc


async def _find_seller_by_store_name(store_name: str) -> dict[str, Any]:
    collection = get_registrations_collection()
    stripped = store_name.strip()
    slug = store_name_to_slug(stripped)
    doc = await collection.find_one({"store_slug": slug})
    if doc is None:
        doc = await collection.find_one(
            {"store_name": {"$regex": f"^{re.escape(stripped)}$", "$options": "i"}}
        )
    if doc is None or doc.get("status") != "approved" or not is_subscription_active(doc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )
    return doc


async def _get_gestor_for_seller(seller_id: str, gestor_id: str) -> dict[str, Any]:
    try:
        gestor_oid = ObjectId(str(gestor_id).strip())
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gestor no encontrado.",
        ) from exc

    doc = await get_gestores_collection().find_one(
        {"_id": gestor_oid, "seller_id": _seller_oid(seller_id)}
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gestor no encontrado.")
    return doc


async def list_seller_gestores(seller_id: str) -> list[GestorPublic]:
    await require_seller_gestores_enabled(seller_id)
    docs = (
        await get_gestores_collection()
        .find({"seller_id": _seller_oid(seller_id)})
        .sort("username", ASCENDING)
        .to_list(length=None)
    )
    return [document_to_gestor_public(doc) for doc in docs]


async def count_seller_gestores(seller_id: str) -> int:
    return int(
        await get_gestores_collection().count_documents({"seller_id": _seller_oid(seller_id)})
    )


def gestor_limit_reached_detail(limit: int) -> str:
    return (
        f"El plan Básico permite hasta {limit} gestores. "
        "Pasa a Premium para gestores ilimitados."
    )


async def create_seller_gestor(seller_id: str, username: str) -> GestorPublic:
    seller = await require_seller_gestores_enabled(seller_id)
    current_count = await count_seller_gestores(seller_id)
    plan_tier = seller.get("plan_tier")
    if not seller_can_add_gestor(plan_tier, current_count):
        limit = max_gestores_for_plan(plan_tier) or 0
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=gestor_limit_reached_detail(limit),
        )

    try:
        doc = build_gestor_document(seller_id=seller_id, username=username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        created = await insert_gestor_document(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un gestor con ese usuario en tu negocio.",
        ) from exc

    return document_to_gestor_public(created)


async def delete_seller_gestor(seller_id: str, gestor_id: str) -> GestorDeleteResult:
    await require_seller_gestores_enabled(seller_id)
    doc = await _get_gestor_for_seller(seller_id, gestor_id)
    gestor_oid = doc["_id"]
    seller_oid = _seller_oid(seller_id)
    await get_gestores_collection().delete_one({"_id": gestor_oid})
    await get_registrations_collection().update_one(
        {"_id": seller_oid},
        {
            "$pull": {"checkout_gestor_ids": str(gestor_oid)},
            "$set": {"updated_at": to_utc_naive(utc_now())},
        },
    )
    return GestorDeleteResult(id=str(gestor_oid), message="Gestor eliminado.")


async def get_seller_gestor_catalog_access(seller_id: str) -> GestorCatalogAccess:
    seller = await require_seller_gestores_enabled(seller_id)
    return parse_gestor_catalog_access(seller.get("gestor_catalog_access"))


async def get_seller_checkout_phones(seller_id: str) -> GestorCheckoutPhones:
    seller = await require_seller_gestores_enabled(seller_id)
    return GestorCheckoutPhones(
        gestor_ids=parse_checkout_gestor_ids(seller.get("checkout_gestor_ids")),
        include_store_phone=parse_checkout_include_store_phone(
            seller.get("checkout_include_store_phone")
        ),
    )


async def update_seller_checkout_phones(
    seller_id: str,
    payload: GestorCheckoutPhonesUpdate,
) -> GestorCheckoutPhones:
    await require_seller_gestores_enabled(seller_id)
    seller_oid = _seller_oid(seller_id)
    try:
        requested = GestorCheckoutPhones(
            gestor_ids=payload.gestor_ids,
            include_store_phone=payload.include_store_phone,
        )
    except ValidationError as exc:
        detail = "Debes dejar al menos un teléfono disponible: el del negocio o uno de tus gestores."
        for err in exc.errors():
            msg = err.get("msg")
            if msg:
                detail = str(msg).removeprefix("Value error, ").strip()
                break
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc

    validated_ids: list[str] = []
    for gestor_id in requested.gestor_ids:
        try:
            gestor_oid = ObjectId(gestor_id)
        except InvalidId as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Gestor no válido: {gestor_id}",
            ) from exc
        doc = await get_gestores_collection().find_one(
            {"_id": gestor_oid, "seller_id": seller_oid},
            {"_id": 1, "phone": 1, "password_hash": 1},
        )
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Algunos gestores no pertenecen a tu red.",
            )
        if not doc.get("password_hash") or not doc.get("phone"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo puedes habilitar gestores activos con teléfono configurado.",
            )
        validated_ids.append(str(doc["_id"]))

    if not requested.include_store_phone and not validated_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes dejar al menos un teléfono disponible: el del negocio o uno de tus gestores.",
        )

    await get_registrations_collection().update_one(
        {"_id": seller_oid},
        {
            "$set": {
                "checkout_gestor_ids": validated_ids,
                "checkout_include_store_phone": requested.include_store_phone,
                "updated_at": to_utc_naive(utc_now()),
            }
        },
    )
    return GestorCheckoutPhones(
        gestor_ids=validated_ids,
        include_store_phone=requested.include_store_phone,
    )


async def resolve_store_checkout_phones(seller: dict[str, Any]) -> list[MarketplaceCheckoutPhonePublic]:
    """Teléfonos disponibles en el checkout del catálogo del negocio (pedido siempre al negocio)."""
    store_phone_digits = seller.get("phone")
    store_name = str(seller.get("store_name") or "Tienda").strip() or "Tienda"
    include_store = parse_checkout_include_store_phone(seller.get("checkout_include_store_phone"))

    options: list[MarketplaceCheckoutPhonePublic] = []

    def append_store_phone() -> None:
        if not store_phone_digits:
            return
        options.append(
            MarketplaceCheckoutPhonePublic(
                key="store",
                kind="store",
                label=store_name,
                phone=phone_display(store_phone_digits),
                username=None,
            )
        )

    if include_store:
        append_store_phone()

    if seller_has_gestores_enabled(seller):
        gestor_ids = parse_checkout_gestor_ids(seller.get("checkout_gestor_ids"))
        if gestor_ids:
            seller_oid = (
                seller["_id"]
                if isinstance(seller.get("_id"), ObjectId)
                else _seller_oid(str(seller["_id"]))
            )
            oids: list[ObjectId] = []
            for gestor_id in gestor_ids:
                try:
                    oids.append(ObjectId(gestor_id))
                except InvalidId:
                    continue
            if oids:
                docs = await get_gestores_collection().find(
                    {
                        "_id": {"$in": oids},
                        "seller_id": seller_oid,
                        "password_hash": {"$exists": True, "$nin": [None, ""]},
                        "phone": {"$exists": True, "$nin": [None, ""]},
                    }
                ).to_list(length=len(oids))
                by_id = {str(doc["_id"]): doc for doc in docs}

                for gestor_id in gestor_ids:
                    doc = by_id.get(gestor_id)
                    if doc is None:
                        continue
                    phone_digits = doc.get("phone")
                    if not phone_digits:
                        continue
                    username = str(doc.get("username") or "").strip()
                    options.append(
                        MarketplaceCheckoutPhonePublic(
                            key=gestor_id,
                            kind="gestor",
                            label=f"@{username}" if username else "Gestor",
                            phone=phone_display(phone_digits),
                            username=username or None,
                        )
                    )

    # Si no queda ninguna opción válida, el negocio sigue siendo el contacto de respaldo.
    if not options:
        append_store_phone()

    return options


async def update_seller_gestor_catalog_access(
    seller_id: str,
    payload: GestorCatalogAccessUpdate,
) -> GestorCatalogAccess:
    await require_seller_gestores_enabled(seller_id)
    seller_oid = _seller_oid(seller_id)
    access = GestorCatalogAccess(mode=payload.mode, product_ids=payload.product_ids)

    if access.mode == "selected" and access.product_ids:
        products_col = get_catalog_products_collection()
        seller_id_str = str(seller_oid)
        owned_ids: set[str] = set()
        for product_id in access.product_ids:
            try:
                oid = ObjectId(product_id)
            except InvalidId as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Producto no válido: {product_id}",
                ) from exc
            exists = await products_col.find_one(
                {"_id": oid, "seller_id": {"$in": [seller_id_str, seller_oid]}},
                {"_id": 1},
            )
            if exists is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Algunos productos no pertenecen a tu catálogo.",
                )
            owned_ids.add(str(exists["_id"]))
        access = GestorCatalogAccess(mode="selected", product_ids=sorted(owned_ids))

    await get_registrations_collection().update_one(
        {"_id": seller_oid},
        {
            "$set": {
                "gestor_catalog_access": gestor_catalog_access_to_document(access),
                "updated_at": to_utc_naive(utc_now()),
            }
        },
    )

    # Quitar del surtido de gestores los productos que ya no están permitidos
    if access.mode == "selected":
        await _prune_gestor_selected_products(seller_oid, set(access.product_ids))

    return access


async def _prune_gestor_selected_products(seller_oid: ObjectId, allowed_ids: set[str]) -> None:
    collection = get_gestores_collection()
    cursor = collection.find({"seller_id": seller_oid})
    async for doc in cursor:
        selected = parse_selected_products(doc.get("selected_products"))
        filtered = [item for item in selected if item.product_id in allowed_ids]
        if len(filtered) == len(selected):
            continue
        await collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "selected_products": selected_products_to_document(filtered),
                    "updated_at": to_utc_naive(utc_now()),
                }
            },
        )


async def _list_seller_product_docs(seller_id: str) -> list[dict[str, Any]]:
    seller_oid = _seller_oid(seller_id)
    seller_id_str = str(seller_oid)
    return (
        await get_catalog_products_collection()
        .find({"seller_id": {"$in": [seller_id_str, seller_oid]}})
        .sort([("sort_order", ASCENDING), ("name", ASCENDING)])
        .to_list(length=None)
    )


async def list_allowed_products_for_seller_network(seller_id: str) -> list[GestorAllowedProductPublic]:
    """Productos del catálogo del negocio con flag de si están en la red de gestores."""
    await require_seller_gestores_enabled(seller_id)
    access = await get_seller_gestor_catalog_access(seller_id)
    products = await _list_seller_product_docs(seller_id)
    result: list[GestorAllowedProductPublic] = []
    for doc in products:
        product_id = str(doc["_id"])
        selected = product_is_allowed_for_gestores(access, product_id)
        if access.mode == "selected" and not selected:
            # En modo selected, el panel del negocio necesita ver todos para marcar checkboxes
            pass
        result.append(
            GestorAllowedProductPublic(
                product_id=product_id,
                name=doc.get("name") or "Producto",
                image_url=doc.get("image_url") or "",
                base_price=float(doc.get("base_price") or 0),
                base_currency=str(doc.get("base_currency") or "CUP"),
                is_available=bool(doc.get("is_available", True)),
                selected=selected,
            )
        )
    return result


async def list_allowed_products_for_gestor(gestor_id: str, seller_id: str) -> list[GestorAllowedProductPublic]:
    access = await get_seller_gestor_catalog_access(seller_id)
    gestor = await _get_gestor_for_seller(seller_id, gestor_id)
    selected_map = {
        item.product_id: item.margin_amount
        for item in parse_selected_products(gestor.get("selected_products"))
    }
    products = await _list_seller_product_docs(seller_id)
    result: list[GestorAllowedProductPublic] = []
    for doc in products:
        product_id = str(doc["_id"])
        if not product_is_allowed_for_gestores(access, product_id):
            continue
        margin = selected_map.get(product_id)
        base_price = float(doc.get("base_price") or 0)
        result.append(
            GestorAllowedProductPublic(
                product_id=product_id,
                name=doc.get("name") or "Producto",
                image_url=doc.get("image_url") or "",
                base_price=base_price,
                base_currency=str(doc.get("base_currency") or "CUP"),
                is_available=bool(doc.get("is_available", True)),
                margin_amount=margin,
                display_price=(
                    compute_gestor_display_price(base_price, margin) if margin is not None else None
                ),
                selected=margin is not None,
            )
        )
    return result


async def update_gestor_selected_products(
    gestor_id: str,
    seller_id: str,
    payload: GestorSelectedProductsUpdate,
) -> GestorPublic:
    access = await get_seller_gestor_catalog_access(seller_id)
    gestor = await _get_gestor_for_seller(seller_id, gestor_id)

    for item in payload.products:
        if not product_is_allowed_for_gestores(access, item.product_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El producto {item.product_id} no está habilitado por el negocio.",
            )

    product_ids = [item.product_id for item in payload.products]
    if product_ids:
        owned = await _list_seller_product_docs(seller_id)
        owned_ids = {str(doc["_id"]) for doc in owned}
        for product_id in product_ids:
            if product_id not in owned_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Algunos productos no existen en el catálogo del negocio.",
                )

    now = to_utc_naive(utc_now())
    await get_gestores_collection().update_one(
        {"_id": gestor["_id"]},
        {
            "$set": {
                "selected_products": selected_products_to_document(payload.products),
                "updated_at": now,
            }
        },
    )
    updated = await get_gestores_collection().find_one({"_id": gestor["_id"]})
    assert updated is not None
    return document_to_gestor_public(updated)


async def login_gestor(
    *,
    store_name: str,
    username: str,
    password: str | None,
) -> GestorLoginResponse:
    seller = await _find_seller_by_store_name(store_name)
    if not seller_has_gestores_enabled(seller):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )
    try:
        normalized_username = validate_gestor_username(username)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        ) from exc

    gestor = await get_gestores_collection().find_one(
        {"seller_id": seller["_id"], "username": normalized_username}
    )
    if gestor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    if not gestor.get("password_hash"):
        setup_token = create_gestor_setup_token(
            gestor_id=str(gestor["_id"]),
            seller_id=str(seller["_id"]),
            username=normalized_username,
            store_name=seller["store_name"],
        )
        return GestorLoginResponse(
            requires_setup=GestorLoginRequiresSetup(
                setup_token=setup_token,
                username=normalized_username,
                store_name=seller["store_name"],
            )
        )

    if not password or not verify_password(password, gestor["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    public = document_to_gestor_public(gestor)
    return GestorLoginResponse(
        access_token=create_gestor_token(
            gestor_id=public.id,
            seller_id=public.seller_id,
            username=public.username,
        ),
        gestor=public,
    )


async def complete_gestor_setup(
    *,
    setup_token: str,
    password: str,
    phone: str,
) -> GestorLoginResponse:
    payload = decode_gestor_setup_token(setup_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El enlace de configuración expiró o no es válido.",
        )

    gestor = await _get_gestor_for_seller(payload["seller_id"], payload["gestor_id"])
    if gestor.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta cuenta ya tiene contraseña. Inicia sesión normalmente.",
        )

    now = to_utc_naive(utc_now())
    await get_gestores_collection().update_one(
        {"_id": gestor["_id"]},
        {
            "$set": {
                "password_hash": hash_password(password),
                "phone": phone,
                "updated_at": now,
            }
        },
    )
    updated = await get_gestores_collection().find_one({"_id": gestor["_id"]})
    assert updated is not None
    public = document_to_gestor_public(updated)
    return GestorLoginResponse(
        access_token=create_gestor_token(
            gestor_id=public.id,
            seller_id=public.seller_id,
            username=public.username,
        ),
        gestor=public,
    )


async def get_gestor_public(gestor_id: str, seller_id: str) -> GestorPublic:
    doc = await _get_gestor_for_seller(seller_id, gestor_id)
    return document_to_gestor_public(doc)
