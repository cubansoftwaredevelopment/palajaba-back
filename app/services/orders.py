import asyncio
from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId

from app.database import get_catalog_products_collection, get_orders_collection, get_registrations_collection
from app.schemas.orders import (
    CreateOrderRequest,
    CreateSellerManualOrderRequest,
    DeliveryInfo,
    OrderItemPublic,
    OrderPublic,
    OrderSubtotalPublic,
    UpdateOrderRequest,
)
from app.services import notifications as notification_service
from app.services.product_popularity import bump_products_on_order_completed
from app.services.subscriptions import is_subscription_active
from app.services.order_totals import compute_order_products_revenue
from app.utils.currency_conversion import VALID_CURRENCIES
from app.utils.datetime import to_utc_naive, utc_now

InvoiceType = Literal["store", "transporter"]


def _calc_subtotals(items: list[dict[str, Any]]) -> list[OrderSubtotalPublic]:
    totals: dict[str, float] = {}
    for item in items:
        currency = item["currency"]
        amount = float(item["unit_price"]) * int(item["quantity"])
        totals[currency] = totals.get(currency, 0.0) + amount

    return [
        OrderSubtotalPublic(currency=currency, amount=round(amount, 2))
        for currency, amount in sorted(totals.items())
    ]


def _normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for item in items:
        quantity = int(item["quantity"])
        unit_price = float(item["unit_price"])
        normalized.append(
            {
                "product_id": str(item["product_id"]),
                "name": item["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "currency": item["currency"],
                "line_total": round(unit_price * quantity, 2),
            }
        )
    return normalized


def _doc_to_public(doc: dict[str, Any]) -> OrderPublic:
    items = _normalize_items(doc.get("items") or [])
    delivery = doc.get("delivery")
    buyer_zone = doc.get("buyer_zone")

    return OrderPublic(
        id=str(doc["_id"]),
        store_id=doc["seller_id"],
        store_name=doc["store_name"],
        status=doc["status"],
        items=[OrderItemPublic(**item) for item in items],
        subtotals=[OrderSubtotalPublic(**entry) for entry in doc.get("subtotals") or []],
        delivery_requested=bool(doc.get("delivery_requested")),
        delivery=DeliveryInfo(**delivery) if delivery else None,
        delivery_price=doc.get("delivery_price"),
        delivery_currency=doc.get("delivery_currency"),
        payment_currency=doc.get("payment_currency"),
        buyer_zone=buyer_zone,
        origin=doc.get("origin") or "platform",
        gestor_id=doc.get("gestor_id"),
        gestor_username=doc.get("gestor_username"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        completed_at=doc.get("completed_at"),
    )


async def ensure_order_indexes() -> None:
    collection = get_orders_collection()
    await collection.create_index([("seller_id", 1), ("created_at", -1)])
    await collection.create_index([("seller_id", 1), ("status", 1), ("created_at", -1)])


async def _get_seller_doc(store_id: str) -> dict[str, Any]:
    try:
        seller_oid = ObjectId(store_id.strip())
    except InvalidId as exc:
        raise ValueError("Tienda no válida.") from exc

    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if seller is None or not is_subscription_active(seller):
        raise ValueError("Tienda no encontrada o no disponible.")

    return seller


async def _get_order_doc(seller_id: str, order_id: str) -> dict[str, Any]:
    try:
        order_oid = ObjectId(order_id.strip())
    except InvalidId as exc:
        raise ValueError("Pedido no válido.") from exc

    doc = await get_orders_collection().find_one({"_id": order_oid, "seller_id": seller_id})
    if doc is None:
        raise ValueError("Pedido no encontrado.")

    return doc


def _items_from_create_payload(items: list) -> list[dict[str, Any]]:
    return [
        {
            "product_id": item.product_id,
            "name": item.name,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "currency": item.currency,
        }
        for item in items
    ]


def _resolve_payment_currency(
    normalized_items: list[dict[str, Any]],
    payment_currency: str | None,
) -> str | None:
    item_currencies = {item["currency"] for item in normalized_items}
    resolved = payment_currency
    if resolved is None and len(item_currencies) == 1:
        resolved = next(iter(item_currencies))
    if resolved and resolved not in VALID_CURRENCIES:
        raise ValueError("Moneda de pago no válida.")
    return resolved


def _build_order_document(
    seller: dict[str, Any],
    *,
    normalized_items: list[dict[str, Any]],
    payment_currency: str | None,
    delivery: DeliveryInfo | None,
    buyer_zone,
    origin: str,
    now,
    gestor_id: str | None = None,
    gestor_username: str | None = None,
) -> dict[str, Any]:
    return {
        "seller_id": str(seller["_id"]),
        "store_name": seller["store_name"],
        "status": "pending_confirmation",
        "items": normalized_items,
        "subtotals": [entry.model_dump() for entry in _calc_subtotals(normalized_items)],
        "delivery_requested": delivery is not None,
        "delivery": delivery.model_dump() if delivery else None,
        "delivery_price": None,
        "delivery_currency": None,
        "payment_currency": payment_currency,
        "buyer_zone": buyer_zone.model_dump() if buyer_zone else None,
        "origin": origin,
        "gestor_id": gestor_id,
        "gestor_username": gestor_username,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }


async def _rollback_stock_decrements(
    adjustments: list[tuple[ObjectId, int]],
) -> None:
    if not adjustments:
        return

    products_col = get_catalog_products_collection()
    now = to_utc_naive(utc_now())
    for product_oid, quantity in reversed(adjustments):
        await products_col.update_one(
            {"_id": product_oid},
            {
                "$inc": {"stock_quantity": quantity},
                "$set": {"is_available": True, "updated_at": now},
            },
        )


async def _decrement_product_stock(
    seller_id: str,
    normalized_items: list[dict[str, Any]],
) -> list[tuple[ObjectId, int]]:
    products_col = get_catalog_products_collection()
    now = to_utc_naive(utc_now())
    qty_by_product: dict[str, int] = {}
    for item in normalized_items:
        product_id = str(item["product_id"])
        qty_by_product[product_id] = qty_by_product.get(product_id, 0) + int(item["quantity"])

    product_oids: list[ObjectId] = []
    for product_id in qty_by_product:
        try:
            product_oids.append(ObjectId(product_id))
        except InvalidId as exc:
            raise ValueError("Producto no válido.") from exc

    product_docs = await products_col.find(
        {"_id": {"$in": product_oids}},
    ).to_list(length=len(product_oids))
    docs_by_id = {str(doc["_id"]): doc for doc in product_docs}

    for product_id in qty_by_product:
        doc = docs_by_id.get(product_id)
        if doc is None:
            raise ValueError("Producto no encontrado.")
        if doc.get("seller_id") != seller_id:
            raise ValueError("No puedes registrar productos de otra tienda.")
        if not doc.get("is_available", True) or doc.get("view_only"):
            raise ValueError(f"«{doc.get('name', 'Producto')}» no está disponible para la venta.")

    applied: list[tuple[ObjectId, int]] = []
    try:
        for product_id, quantity in qty_by_product.items():
            doc = docs_by_id[product_id]
            if doc.get("stock_quantity") is None:
                continue

            product_oid = ObjectId(product_id)
            result = await products_col.update_one(
                {
                    "_id": product_oid,
                    "seller_id": seller_id,
                    "stock_quantity": {"$gte": quantity},
                },
                [
                    {
                        "$set": {
                            "stock_quantity": {"$subtract": ["$stock_quantity", quantity]},
                            "updated_at": now,
                        }
                    },
                    {
                        "$set": {
                            "is_available": {"$gt": ["$stock_quantity", 0]},
                        }
                    },
                ],
            )
            if result.modified_count != 1:
                raise ValueError(
                    f"Stock insuficiente para «{doc.get('name', 'producto')}»."
                )
            applied.append((product_oid, quantity))
    except Exception:
        await _rollback_stock_decrements(applied)
        raise

    return applied


async def create_order(payload: CreateOrderRequest) -> OrderPublic:
    seller = await _get_seller_doc(payload.store_id)
    normalized_items = _normalize_items(_items_from_create_payload(payload.items))
    payment_currency = _resolve_payment_currency(normalized_items, payload.payment_currency)
    now = to_utc_naive(utc_now())

    doc = _build_order_document(
        seller,
        normalized_items=normalized_items,
        payment_currency=payment_currency,
        delivery=payload.delivery,
        buyer_zone=payload.buyer_zone,
        origin="platform",
        now=now,
        gestor_id=payload.gestor_id,
        gestor_username=payload.gestor_username,
    )

    result = await get_orders_collection().insert_one(doc)
    doc["_id"] = result.inserted_id

    item_count = sum(int(item["quantity"]) for item in normalized_items)
    await notification_service.notify_seller_new_order(
        seller["_id"],
        result.inserted_id,
        item_count=item_count,
        delivery_requested=bool(doc["delivery_requested"]),
    )

    return _doc_to_public(doc)


async def create_seller_manual_order(
    seller_id: str,
    payload: CreateSellerManualOrderRequest,
) -> OrderPublic:
    try:
        seller_oid = ObjectId(seller_id.strip())
    except InvalidId as exc:
        raise ValueError("Tienda no válida.") from exc

    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if seller is None or not is_subscription_active(seller):
        raise ValueError("Tienda no encontrada o no disponible.")

    normalized_items = _normalize_items(_items_from_create_payload(payload.items))
    payment_currency = _resolve_payment_currency(normalized_items, payload.payment_currency)
    stock_adjustments = await _decrement_product_stock(seller_id, normalized_items)
    now = to_utc_naive(utc_now())

    doc = _build_order_document(
        seller,
        normalized_items=normalized_items,
        payment_currency=payment_currency,
        delivery=payload.delivery,
        buyer_zone=payload.buyer_zone,
        origin="manual",
        now=now,
    )

    try:
        result = await get_orders_collection().insert_one(doc)
    except Exception:
        await _rollback_stock_decrements(stock_adjustments)
        raise

    doc["_id"] = result.inserted_id
    return _doc_to_public(doc)


async def list_seller_orders(seller_id: str) -> list[OrderPublic]:
    cursor = (
        get_orders_collection()
        .find({"seller_id": seller_id})
        .sort([("created_at", -1)])
    )
    docs = await cursor.to_list(length=None)
    return [_doc_to_public(doc) for doc in docs]


async def update_seller_order(
    seller_id: str,
    order_id: str,
    payload: UpdateOrderRequest,
) -> OrderPublic:
    doc = await _get_order_doc(seller_id, order_id)

    if doc["status"] == "completed" and payload.status == "pending_confirmation":
        raise ValueError("No puedes volver un pedido a pendiente.")

    if payload.items is not None:
        if doc["status"] == "completed":
            raise ValueError("No puedes editar productos de un pedido ya realizado.")
        if not payload.items:
            raise ValueError("El pedido debe tener al menos un producto.")

        raw_items = [
            {
                "product_id": item.product_id,
                "name": item.name,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "currency": item.currency.strip().upper(),
            }
            for item in payload.items
        ]
        normalized_items = _normalize_items(raw_items)
        doc["items"] = normalized_items
        doc["subtotals"] = [entry.model_dump() for entry in _calc_subtotals(normalized_items)]

    updates: dict[str, Any] = {}
    now = to_utc_naive(utc_now())
    updates["updated_at"] = now

    if payload.items is not None:
        updates["items"] = doc["items"]
        updates["subtotals"] = doc["subtotals"]

    if payload.delivery_price is not None:
        updates["delivery_price"] = float(payload.delivery_price)

    if payload.delivery_currency is not None:
        updates["delivery_currency"] = payload.delivery_currency

    if payload.payment_currency is not None:
        if payload.payment_currency not in VALID_CURRENCIES:
            raise ValueError("Moneda de pago no válida.")
        updates["payment_currency"] = payload.payment_currency

    if payload.status is not None:
        if payload.status == "completed":
            if doc.get("delivery_requested"):
                resolved_delivery_price = (
                    payload.delivery_price
                    if payload.delivery_price is not None
                    else doc.get("delivery_price")
                )
                if resolved_delivery_price is None:
                    raise ValueError(
                        "Indica el precio del domicilio antes de marcar el pedido como realizado."
                    )

            resolved_payment_currency = (
                payload.payment_currency
                if payload.payment_currency is not None
                else doc.get("payment_currency")
            )
            if not resolved_payment_currency:
                raise ValueError(
                    "Selecciona la moneda de pago antes de marcar el pedido como realizado."
                )

            updates["status"] = "completed"
            updates["completed_at"] = now
            merged_doc = {**doc, **updates}
            revenue = compute_order_products_revenue(merged_doc)
            if revenue is not None:
                _, collected_total = revenue
                updates["collected_total"] = collected_total
            else:
                updates["collected_total"] = None
        else:
            updates["status"] = payload.status
            updates["completed_at"] = None
            updates["collected_total"] = None

    if len(updates) == 1 and updates.get("updated_at"):
        return _doc_to_public(doc)

    completing_order = (
        payload.status == "completed"
        and doc["status"] != "completed"
    )
    items_for_popularity = updates.get("items") or doc.get("items") or []

    await get_orders_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": updates},
    )

    if completing_order:
        await bump_products_on_order_completed(items_for_popularity)

    updated = await get_orders_collection().find_one({"_id": doc["_id"]})
    return _doc_to_public(updated)


async def delete_seller_order(seller_id: str, order_id: str) -> None:
    doc = await _get_order_doc(seller_id, order_id)

    if doc["status"] != "pending_confirmation":
        raise ValueError("Solo puedes cancelar pedidos pendientes de confirmar.")

    await get_orders_collection().delete_one({"_id": doc["_id"]})


async def generate_order_invoice_pdf(
    seller_id: str,
    order_id: str,
    invoice_type: InvoiceType,
) -> tuple[bytes, str]:
    doc = await _get_order_doc(seller_id, order_id)
    seller = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
    if seller is None:
        raise ValueError("Tienda no encontrada.")

    from app.services.order_invoice import build_order_invoice_pdf

    pdf_bytes = await asyncio.to_thread(build_order_invoice_pdf, doc, seller, invoice_type)
    order_code = str(doc["_id"])[-6:].upper()
    suffix = "tienda" if invoice_type == "store" else "transportista"
    filename = f"pedido-{order_code}-{suffix}.pdf"
    return pdf_bytes, filename
