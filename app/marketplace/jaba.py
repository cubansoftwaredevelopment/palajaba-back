"""Jaba compartida y sincronización de productos guardados."""

from typing import Any
from bson import ObjectId
from bson.errors import InvalidId
from app.database import get_catalog_products_collection, get_registrations_collection
from app.marketplace.schemas import (
    JabaRemovedProductPublic,
    JabaSyncPublic,
    JabaSyncRequest,
    MarketplaceProductPublic,
    MarketplaceSharedProductsPublic,
)
from app.products.sales_areas import product_covers_municipality
from app.auth.seller_profile import is_profile_complete
from app.subscriptions.service import is_subscription_active
from app.marketplace.products import _load_zone_product, _product_to_public
from app.marketplace.queries import _catalog_product_name
from app.marketplace.sellers import _build_marketplace_seller_context
from app.marketplace.utils import _selected_sales_area_municipality_ids, _validate_location_ids

def parse_shared_jaba_item(raw: str) -> tuple[str, int] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    product_id, _, quantity_raw = text.partition(".")
    product_id = product_id.strip()
    if not product_id:
        return None
    try:
        quantity = int(quantity_raw) if quantity_raw.strip() else 1
    except ValueError:
        quantity = 1
    return product_id, min(99, max(1, quantity))

async def list_shared_products(
    province_id: str,
    municipality_id: str,
    items: list[str],
) -> MarketplaceSharedProductsPublic:
    _validate_location_ids(province_id, municipality_id)
    seller_by_id, local_ids, delivery_ids, pickup_ids = await _build_marketplace_seller_context(
        province_id,
        municipality_id,
    )
    products: list[MarketplaceProductPublic] = []
    unavailable: list[str] = []
    seen: set[str] = set()
    for raw in items:
        parsed = parse_shared_jaba_item(raw)
        if parsed is None:
            continue
        product_id, _quantity = parsed
        if product_id in seen:
            continue
        seen.add(product_id)
        try:
            products.append(
                await _load_zone_product(
                    seller_by_id,
                    local_ids,
                    delivery_ids,
                    pickup_ids,
                    product_id,
                    province_id=province_id,
                    municipality_id=municipality_id,
                )
            )
        except ValueError:
            unavailable.append(await _catalog_product_name(product_id))
    return MarketplaceSharedProductsPublic(products=products, unavailable=unavailable)

JABA_REMOVAL_MESSAGES: dict[str, str] = {
    "deleted": "Ya no está en el catálogo de la tienda.",
    "unavailable": "Está agotado y no se puede comprar por ahora.",
    "view_only": "Es solo para consulta y no admite compra directa.",
    "store_unavailable": "La tienda ya no está disponible o no atiende en tu zona.",
    "no_delivery": "No tiene entrega a domicilio en tu municipio.",
    "out_of_zone": "Este producto no se vende en tu municipio.",
}

def _jaba_removal_message(reason: str) -> str:
    return JABA_REMOVAL_MESSAGES.get(reason, "Ya no se puede comprar.")

def _jaba_product_eligible(
    product: dict[str, Any],
    seller: dict[str, Any] | None,
    *,
    province_id: str | None,
    municipality_id: str | None,
    municipality_ids: list[str] | None,
    visible_seller_ids: set[str] | None,
    pickup_seller_ids: set[str] | None = None,
) -> str | None:
    if seller is None:
        return "store_unavailable" if visible_seller_ids is not None else "deleted"

    seller_id = str(seller["_id"])
    if visible_seller_ids is not None:
        if seller_id not in visible_seller_ids:
            return "store_unavailable"
    elif not is_subscription_active(seller) or not is_profile_complete(seller):
        return "store_unavailable"

    if product.get("view_only"):
        return "view_only"

    if not product.get("is_available", True):
        return "unavailable"

    if province_id and municipality_ids and visible_seller_ids is not None:
        if not any(
            product_covers_municipality(product, province_id, selected_id)
            for selected_id in municipality_ids
        ):
            return "out_of_zone"

    return None

async def sync_jaba_products(payload: JabaSyncRequest) -> JabaSyncPublic:
    if not payload.items:
        return JabaSyncPublic()

    province_id = payload.province_id.strip() if payload.province_id else None
    municipality_id = payload.municipality_id.strip() if payload.municipality_id else None
    visible_sellers: dict[str, dict[str, Any]] | None = None
    visible_seller_ids: set[str] | None = None
    pickup_seller_ids: set[str] | None = None

    selected_municipality_ids: list[str] = []
    if province_id and municipality_id:
        _validate_location_ids(province_id, municipality_id)
        selected_municipality_ids = _selected_sales_area_municipality_ids(
            province_id,
            municipality_id,
            payload.municipios_adicionales,
        )
        visible_sellers, _, _, pickup_list = await _build_marketplace_seller_context(
            province_id,
            municipality_id,
            municipios_adicionales=payload.municipios_adicionales,
        )
        visible_seller_ids = set(visible_sellers.keys())
        pickup_seller_ids = set(pickup_list)

    products_col = get_catalog_products_collection()
    registrations = get_registrations_collection()

    product_ids: list[str] = []
    names_by_id: dict[str, str] = {}
    for item in payload.items:
        product_id = item.product_id.strip()
        if not product_id or product_id in names_by_id:
            continue
        product_ids.append(product_id)
        names_by_id[product_id] = item.name.strip() or "Producto"

    object_ids: list[ObjectId] = []
    for product_id in product_ids:
        try:
            object_ids.append(ObjectId(product_id))
        except InvalidId:
            continue

    docs_by_id: dict[str, dict[str, Any]] = {}
    if object_ids:
        cursor = products_col.find({"_id": {"$in": object_ids}})
        async for doc in cursor:
            docs_by_id[str(doc["_id"])] = doc

    seller_ids = {doc["seller_id"] for doc in docs_by_id.values()}
    seller_by_id: dict[str, dict[str, Any]] = {}
    if visible_sellers is not None:
        seller_by_id = visible_sellers
    elif seller_ids:
        seller_oids = []
        for seller_id in seller_ids:
            try:
                seller_oids.append(ObjectId(seller_id))
            except InvalidId:
                continue
        if seller_oids:
            seller_docs = await registrations.find({"_id": {"$in": seller_oids}}).to_list(length=None)
            seller_by_id = {str(doc["_id"]): doc for doc in seller_docs}

    valid: list[MarketplaceProductPublic] = []
    removed: list[JabaRemovedProductPublic] = []

    for product_id in product_ids:
        display_name = names_by_id.get(product_id, "Producto")
        doc = docs_by_id.get(product_id)
        if doc is None:
            removed.append(
                JabaRemovedProductPublic(
                    product_id=product_id,
                    name=display_name,
                    reason="deleted",
                    message=_jaba_removal_message("deleted"),
                )
            )
            continue

        seller = seller_by_id.get(doc.get("seller_id"))
        if seller is None and visible_sellers is None:
            try:
                seller = await registrations.find_one({"_id": ObjectId(doc["seller_id"])})
            except InvalidId:
                seller = None

        reason = _jaba_product_eligible(
            doc,
            seller,
            province_id=province_id,
            municipality_id=municipality_id,
            municipality_ids=selected_municipality_ids,
            visible_seller_ids=visible_seller_ids,
            pickup_seller_ids=pickup_seller_ids,
        )
        if reason:
            removed.append(
                JabaRemovedProductPublic(
                    product_id=product_id,
                    name=doc.get("name") or display_name,
                    reason=reason,
                    message=_jaba_removal_message(reason),
                )
            )
            continue

        public_sellers = visible_sellers if visible_sellers is not None else seller_by_id
        public = _product_to_public(
            doc,
            public_sellers,
            buyer_province_id=province_id,
            buyer_municipality_id=municipality_id,
            buyer_municipality_ids=[
                selected_id
                for selected_id in selected_municipality_ids
                if selected_id != municipality_id
            ],
        )
        if public is None:
            removed.append(
                JabaRemovedProductPublic(
                    product_id=product_id,
                    name=doc.get("name") or display_name,
                    reason="store_unavailable",
                    message=_jaba_removal_message("store_unavailable"),
                )
            )
            continue

        valid.append(public)

    return JabaSyncPublic(valid=valid, removed=removed)
