"""Ficha pública de un producto y carga dentro de la zona del comprador."""

from typing import Any
from app.database import get_catalog_products_collection
from app.marketplace.schemas import MarketplaceProductPublic
from app.products.sales_areas import product_covers_municipality
from app.products.service import public_product_images
from app.products.utils import (
    public_discount_percent,
    public_stock,
    public_unit_amount,
)
from app.marketplace.queries import _zone_visible_product_query
from app.marketplace.sellers import (
    _build_marketplace_seller_context,
    _product_pickup_info,
    _service_fee_for_seller,
    _store_to_public,
)
from app.marketplace.utils import (
    _display_category_name,
    _product_object_id,
    _validate_location_ids,
)

def _product_to_public(
    product: dict[str, Any],
    seller_by_id: dict[str, dict[str, Any]],
    *,
    buyer_province_id: str | None = None,
    buyer_municipality_id: str | None = None,
    buyer_municipality_ids: list[str] | None = None,
) -> MarketplaceProductPublic | None:
    seller_id = product.get("seller_id")
    seller = seller_by_id.get(seller_id)
    if seller is None:
        return None

    pickup_required = False
    pickup_municipality_name = None
    pickup_notice = None
    if buyer_province_id and buyer_municipality_id:
        selected_municipalities = list(dict.fromkeys(
            [buyer_municipality_id, *(buyer_municipality_ids or [])]
        ))
        available_municipality_id = next(
            (
                municipality_id
                for municipality_id in selected_municipalities
                if product_covers_municipality(product, buyer_province_id, municipality_id)
            ),
            None,
        )
        if available_municipality_id is None:
            return None
        pickup_required, pickup_municipality_name = _product_pickup_info(
            product,
            seller,
            buyer_province_id,
            available_municipality_id,
        )
        if pickup_required:
            if pickup_municipality_name:
                pickup_notice = (
                    f"Sin domicilio a tu municipio · Recoger en {pickup_municipality_name}"
                )
            else:
                pickup_notice = "Sin domicilio a tu municipio"

    global_category_id = str(product.get("global_category_id") or "otros").strip().lower()
    images = public_product_images(product)
    frontal_url = next((image.image_url for image in images if image.is_frontal), None)
    return MarketplaceProductPublic(
        id=str(product["_id"]),
        global_category_id=global_category_id,
        name=product["name"],
        description=product.get("description"),
        image_url=frontal_url or product["image_url"],
        images=images,
        base_price=float(product["base_price"]),
        base_currency=product["base_currency"],
        service_fee_percent=_service_fee_for_seller(seller),
        discount_percent=public_discount_percent(product, seller),
        accepted_currencies=list(product.get("accepted_currencies") or []),
        offers_delivery=bool(product.get("offers_delivery")),
        stock_quantity=public_stock(product)[0],
        stock_unit=public_stock(product)[1],
        unit_amount=public_unit_amount(product),
        is_available=bool(product.get("is_available", True)),
        view_only=bool(product.get("view_only")),
        pickup_required=pickup_required,
        pickup_municipality_name=pickup_municipality_name,
        pickup_notice=pickup_notice,
        store=_store_to_public(seller),
        category_name=_display_category_name(global_category_id),
    )

async def _load_zone_product(
    seller_by_id: dict[str, dict[str, Any]],
    local_seller_ids: list[str],
    delivery_seller_ids: list[str],
    pickup_seller_ids: list[str],
    product_id: str,
    *,
    province_id: str,
    municipality_id: str,
) -> MarketplaceProductPublic:
    query = _zone_visible_product_query(
        local_seller_ids,
        delivery_seller_ids,
        pickup_seller_ids=pickup_seller_ids or None,
        extra={"_id": _product_object_id(product_id)},
        province_id=province_id,
        municipality_id=municipality_id,
    )
    if query.get("_id") == {"$exists": False}:
        raise ValueError("Producto no encontrado.")
    doc = await get_catalog_products_collection().find_one(query)
    if doc is None:
        raise ValueError("Producto no encontrado.")
    product = _product_to_public(
        doc,
        seller_by_id,
        buyer_province_id=province_id,
        buyer_municipality_id=municipality_id,
    )
    if product is None:
        raise ValueError("Producto no encontrado.")
    return product

async def get_marketplace_product(
    product_id: str,
    province_id: str,
    municipality_id: str,
) -> MarketplaceProductPublic:
    _validate_location_ids(province_id, municipality_id)
    seller_by_id, local_ids, delivery_ids, pickup_ids = await _build_marketplace_seller_context(
        province_id,
        municipality_id,
    )
    return await _load_zone_product(
        seller_by_id,
        local_ids,
        delivery_ids,
        pickup_ids,
        product_id,
        province_id=province_id,
        municipality_id=municipality_id,
    )
