from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.auth.utils import (
    create_mensajero_setup_token,
    create_mensajero_token,
    decode_mensajero_setup_token,
    hash_password,
    verify_password,
)
from app.database import (
    get_mensajeria_asignaciones_collection,
    get_mensajeria_batches_collection,
    get_mensajeria_puntos_collection,
    get_customers_collection,
    get_mensajeros_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.live.hub import customer_hub, hub, publish_customer_notification, publish_seller_data_update
from app.live.push import notify_device_tokens
from app.mensajeros.devices import list_device_tokens
from app.mensajeros.utils import ACTIVE_ASSIGNMENT, VEHICLE_TYPES, haversine_km, normalize_username
from app.notifications.service import notify_seller_notice
from app.payments.qvapay import verify_qvapay_username
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.phone import normalize_phone_digits, phone_display

OPEN_ASSIGNMENT = ("assigned", "in_route", "closed")


def _oid(value: str, message: str = "Identificador no válido.") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError) as exc:
        raise HTTPException(status_code=422, detail=message) from exc


def _public(doc: dict[str, Any]) -> dict[str, Any]:
    vehicles = doc.get("vehicles") or []
    return {
        "id": str(doc["_id"]),
        "seller_id": str(doc["seller_id"]),
        "first_name": doc.get("first_name") or "",
        "last_name": doc.get("last_name") or "",
        "phone": phone_display(doc["phone"]) if doc.get("phone") else "",
        "username": doc.get("username") or "",
        "has_password": bool(doc.get("password_hash")),
        "profile_photo_url": doc.get("profile_photo_url"),
        "qvapay_username": doc.get("qvapay_username"),
        "qvapay_verified": bool(doc.get("qvapay_username") and doc.get("qvapay_verified_at")),
        "vehicle_types": sorted({item.get("vehicle_type") for item in vehicles if item.get("vehicle_type")}),
        "vehicles": [
            {
                "id": item.get("id"),
                "vehicle_type": item.get("vehicle_type"),
                "plate": item.get("plate") or "",
                "photo_url": (_vehicle_photo_urls(item) or [None])[0],
                "photo_urls": _vehicle_photo_urls(item),
            }
            for item in vehicles
        ],
        "is_active": doc.get("is_active", True) is not False,
    }


async def ensure_mensajero_indexes() -> None:
    await get_mensajeros_collection().create_index([("username", ASCENDING)], unique=True)
    await get_mensajeros_collection().create_index([("seller_id", ASCENDING)])
    await get_mensajeria_batches_collection().create_index(
        [("client_id", ASCENDING)], unique=True, partialFilterExpression={"client_id": {"$type": "string"}}
    )
    await get_mensajeria_asignaciones_collection().create_index(
        [("order_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": {"$in": ["assigned", "in_route"]}},
    )
    await get_mensajeria_asignaciones_collection().create_index([("batch_id", ASCENDING)])
    await get_mensajeria_asignaciones_collection().create_index(
        [("client_id", ASCENDING)], unique=True, partialFilterExpression={"client_id": {"$type": "string"}}
    )
    await get_mensajeria_puntos_collection().create_index([("client_id", ASCENDING)], unique=True)
    await get_mensajeria_puntos_collection().create_index([("batch_id", ASCENDING), ("recorded_at", ASCENDING)])


async def assert_mensajero_active(mensajero_id: str) -> dict[str, Any]:
    doc = await get_mensajeros_collection().find_one({"_id": _oid(mensajero_id, "Mensajero no encontrado.")})
    if not doc or doc.get("is_active", True) is False:
        raise HTTPException(status_code=401, detail="La cuenta del mensajero no está activa.")
    return doc


async def list_for_seller(seller_id: str, *, search: str = "", vehicle_type: str = "") -> list[dict]:
    query: dict[str, Any] = {"seller_id": _oid(seller_id, "Tienda no encontrada.")}
    if vehicle_type:
        if vehicle_type not in VEHICLE_TYPES:
            raise HTTPException(status_code=422, detail="Tipo de vehículo no válido.")
        query["vehicles.vehicle_type"] = vehicle_type
    docs = await get_mensajeros_collection().find(query).sort("first_name", ASCENDING).to_list(length=200)
    needle = search.strip().lower()
    if needle:
        docs = [
            doc for doc in docs
            if needle in f"{doc.get('first_name', '')} {doc.get('last_name', '')}".lower()
        ]
    counts = await open_assignment_counts([doc["_id"] for doc in docs])
    items = []
    for doc in docs:
        item = _public(doc)
        item["open_assignments"] = counts.get(item["id"], 0)
        items.append(item)
    return items


async def create_for_seller(seller_id: str, payload) -> dict:
    username = normalize_username(payload.username)
    try:
        phone = normalize_phone_digits(payload.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = to_utc_naive(utc_now())
    document = {
        "seller_id": _oid(seller_id, "Tienda no encontrada."),
        "first_name": payload.first_name.strip(),
        "last_name": payload.last_name.strip(),
        "phone": phone,
        "username": username,
        "password_hash": None,
        "profile_photo_url": None,
        "qvapay_username": None,
        "qvapay_verified_at": None,
        "vehicles": [],
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await get_mensajeros_collection().insert_one(document)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Ese alias ya existe.") from exc
    document["_id"] = result.inserted_id
    return _public(document)


async def _owned_messenger(seller_id: str, mensajero_id: str) -> dict:
    doc = await get_mensajeros_collection().find_one({
        "_id": _oid(mensajero_id, "Mensajero no encontrado."),
        "seller_id": _oid(seller_id, "Tienda no encontrada."),
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Ese mensajero no es de tu tienda.")
    return doc


async def open_assignment_counts(mensajero_ids: list) -> dict[str, int]:
    if not mensajero_ids:
        return {}
    rows = await get_mensajeria_asignaciones_collection().aggregate([
        {"$match": {"mensajero_id": {"$in": mensajero_ids}, "status": {"$in": list(ACTIVE_ASSIGNMENT)}}},
        {"$group": {"_id": "$mensajero_id", "count": {"$sum": 1}}},
    ]).to_list(length=len(mensajero_ids))
    return {str(row["_id"]): int(row["count"]) for row in rows}


async def update_for_seller(seller_id: str, mensajero_id: str, payload) -> dict:
    doc = await _owned_messenger(seller_id, mensajero_id)
    username = normalize_username(payload.username)
    try:
        phone = normalize_phone_digits(payload.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = to_utc_naive(utc_now())
    changes = {
        "first_name": payload.first_name.strip(),
        "last_name": payload.last_name.strip(),
        "phone": phone,
        "username": username,
        "updated_at": now,
    }
    try:
        await get_mensajeros_collection().update_one({"_id": doc["_id"]}, {"$set": changes})
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Ese alias ya existe.") from exc
    doc.update(changes)
    return _public(doc)


async def delete_for_seller(seller_id: str, mensajero_id: str) -> None:
    doc = await _owned_messenger(seller_id, mensajero_id)
    open_count = await get_mensajeria_asignaciones_collection().count_documents({
        "mensajero_id": doc["_id"],
        "status": {"$in": list(ACTIVE_ASSIGNMENT)},
    })
    if open_count:
        raise HTTPException(status_code=409, detail="No se puede eliminar: tiene pedidos asignados.")
    await get_mensajeros_collection().delete_one({"_id": doc["_id"]})


async def login(username: str, password: str | None) -> dict:
    normalized = normalize_username(username)
    doc = await get_mensajeros_collection().find_one({"username": normalized})
    if not doc or doc.get("is_active", True) is False:
        raise HTTPException(status_code=401, detail="No encontramos ese mensajero.")
    if not doc.get("password_hash"):
        token = create_mensajero_setup_token(
            mensajero_id=str(doc["_id"]),
            seller_id=str(doc["seller_id"]),
            username=normalized,
        )
        return {"requires_setup": {"setup_token": token, "username": normalized}}
    if not password or not verify_password(password, doc["password_hash"]):
        raise HTTPException(status_code=401, detail="La contraseña no coincide.")
    access = create_mensajero_token(
        mensajero_id=str(doc["_id"]),
        seller_id=str(doc["seller_id"]),
        username=normalized,
    )
    return {"access_token": access, "mensajero": _public(doc)}


async def complete_setup(setup_token: str, password: str) -> dict:
    payload = decode_mensajero_setup_token(setup_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="El enlace de alta expiró. Entra de nuevo.")
    doc = await assert_mensajero_active(payload["mensajero_id"])
    if doc.get("password_hash"):
        raise HTTPException(status_code=409, detail="Esta cuenta ya tiene contraseña.")
    now = to_utc_naive(utc_now())
    await get_mensajeros_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": {"password_hash": hash_password(password), "updated_at": now}},
    )
    doc["password_hash"] = "set"
    access = create_mensajero_token(
        mensajero_id=str(doc["_id"]),
        seller_id=str(doc["seller_id"]),
        username=doc["username"],
    )
    return {"access_token": access, "mensajero": _public(doc)}


async def assignment_map(order_ids: list[ObjectId]) -> dict[str, dict]:
    if not order_ids:
        return {}
    docs = await get_mensajeria_asignaciones_collection().find(
        {"order_id": {"$in": order_ids}, "status": {"$in": list(OPEN_ASSIGNMENT)}}
    ).sort("created_at", DESCENDING).to_list(length=500)
    found: dict[str, dict] = {}
    for doc in docs:
        key = str(doc["order_id"])
        if key in found:
            continue
        batch = await get_mensajeria_batches_collection().find_one({"_id": doc["batch_id"]})
        evidence = doc.get("evidence") if isinstance(doc.get("evidence"), dict) else None
        found[key] = {
            "assignment_id": str(doc["_id"]),
            "batch_id": str(doc["batch_id"]),
            "status": doc.get("status"),
            "route_started": (batch or {}).get("status") == "in_progress",
            "pay_via": doc.get("pay_via"),
            "fee_amount": doc.get("fee_amount"),
            "fee_currency": doc.get("fee_currency"),
            "evidence": None if not evidence else {
                "note": evidence.get("note") or "",
                "images": [str(url) for url in (evidence.get("images") or []) if url],
                "submitted_at": evidence.get("submitted_at").isoformat() if evidence.get("submitted_at") else None,
            },
        }
    return found


def _order_brief(order: dict) -> dict:
    delivery = order.get("delivery") or {}
    qvapay = order.get("qvapay") or {}
    return {
        "id": str(order["_id"]),
        "code": str(order["_id"])[-6:].upper(),
        "buyer_name": order.get("buyer_name") or delivery.get("recipient_name") or "Cliente",
        "address": delivery.get("address") or "",
        "latitude": delivery.get("latitude"),
        "longitude": delivery.get("longitude"),
        "phone": delivery.get("phone_primary") or order.get("buyer_phone"),
        "items": [
            {"name": item.get("name") or "Producto", "quantity": int(item.get("quantity") or 1)}
            for item in (order.get("items") or [])
        ],
        "payment_method": order.get("payment_method") or "contact",
        "delivery_price": order.get("delivery_price"),
        "delivery_currency": order.get("delivery_currency"),
        "delivery_amount_usd": qvapay.get("delivery_amount_usd"),
        "status": order.get("status"),
    }


async def assign_batch(seller_id: str, payload) -> dict:
    window_start = to_utc_naive(payload.window_start)
    window_end = to_utc_naive(payload.window_end)
    if window_end <= window_start:
        raise HTTPException(status_code=422, detail="La hora final tiene que ser posterior a la inicial.")
    messenger = await get_mensajeros_collection().find_one({
        "_id": _oid(payload.mensajero_id, "Mensajero no encontrado."),
        "seller_id": _oid(seller_id, "Tienda no encontrada."),
    })
    if not messenger:
        raise HTTPException(status_code=404, detail="Ese mensajero no es de tu tienda.")
    if payload.client_id:
        existing = await get_mensajeria_batches_collection().find_one({"client_id": payload.client_id})
        if existing:
            return await _batch_public(existing)
    now = to_utc_naive(utc_now())
    prepared = []
    for item in payload.orders:
        order = await get_orders_collection().find_one({"_id": _oid(item.order_id, "Pedido no encontrado."), "seller_id": seller_id})
        if not order or not order.get("delivery_requested") or order.get("status") == "cancelled":
            raise HTTPException(status_code=409, detail="Solo puedes asignar pedidos con mensajería que no estén cancelados.")
        if order.get("payment_method") == "qvapay" and (order.get("qvapay") or {}).get("payment_status") != "paid":
            raise HTTPException(status_code=409, detail="El cliente todavía no pagó este pedido por QvaPay.")
        active = await get_mensajeria_asignaciones_collection().find_one(
            {"order_id": order["_id"], "status": {"$in": list(ACTIVE_ASSIGNMENT)}}
        )
        if active:
            raise HTTPException(status_code=409, detail="Uno de los pedidos ya tiene mensajero.")
        fee_usd = None
        if item.pay_via == "qvapay":
            if order.get("payment_method") != "qvapay":
                raise HTTPException(status_code=409, detail="Solo un pedido pagado por QvaPay puede pagarse al mensajero por QvaPay.")
            if not messenger.get("qvapay_username") or not messenger.get("qvapay_verified_at"):
                raise HTTPException(status_code=409, detail="Este mensajero no tiene QvaPay verificado.")
            price = order.get("delivery_price")
            if price is None:
                raise HTTPException(status_code=409, detail="Fija el precio de la mensajería antes de pagarla por QvaPay.")
            if item.fee_currency != (order.get("delivery_currency") or item.fee_currency):
                raise HTTPException(status_code=422, detail="El cobro QvaPay usa la moneda de la mensajería del pedido.")
            if float(item.fee_amount) > float(price):
                raise HTTPException(status_code=422, detail="El cobro no puede superar el precio de la mensajería.")
            delivery_usd = float((order.get("qvapay") or {}).get("delivery_amount_usd") or 0)
            fee_usd = round(delivery_usd * (float(item.fee_amount) / float(price)), 2) if float(price) else 0
            if fee_usd > delivery_usd:
                fee_usd = delivery_usd
        elif item.fee_currency not in ("CUP", "USD", "EUR", "MLC", "QUSD"):
            raise HTTPException(status_code=422, detail="Moneda no válida.")
        prepared.append((order, item, fee_usd))
    batch = {
        "client_id": payload.client_id,
        "seller_id": _oid(seller_id, "Tienda no encontrada."),
        "mensajero_id": messenger["_id"],
        "status": "assigned",
        "vehicle_id": None,
        "window_start": window_start,
        "window_end": window_end,
        "started_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        inserted = await get_mensajeria_batches_collection().insert_one(batch)
    except DuplicateKeyError:
        existing = await get_mensajeria_batches_collection().find_one({"client_id": payload.client_id})
        return await _batch_public(existing)
    batch["_id"] = inserted.inserted_id
    for order, item, fee_usd in prepared:
        await get_mensajeria_asignaciones_collection().insert_one({
            "batch_id": batch["_id"],
            "order_id": order["_id"],
            "seller_id": _oid(seller_id, "Tienda no encontrada."),
            "mensajero_id": messenger["_id"],
            "pay_via": item.pay_via,
            "fee_amount": float(item.fee_amount),
            "fee_currency": item.fee_currency,
            "fee_amount_usd": fee_usd,
            "status": "assigned",
            "evidence": None,
            "created_at": now,
            "updated_at": now,
        })
    await _push_mensajero(
        str(messenger["_id"]),
        "Nueva mensajería",
        f"La tienda te asignó {len(prepared)} pedido{'s' if len(prepared) != 1 else ''}.",
    )
    return await _batch_public(batch)


async def cancel_assignment(seller_id: str, order_id: str) -> dict:
    order_oid = _oid(order_id, "Pedido no encontrado.")
    assignment = await get_mensajeria_asignaciones_collection().find_one({
        "order_id": order_oid,
        "seller_id": _oid(seller_id, "Tienda no encontrada."),
        "status": "assigned",
    })
    if not assignment:
        raise HTTPException(status_code=409, detail="Este pedido no tiene una asignación que se pueda cancelar.")
    batch = await get_mensajeria_batches_collection().find_one({"_id": assignment["batch_id"]})
    if not batch or batch.get("status") != "assigned":
        raise HTTPException(status_code=409, detail="La ruta ya comenzó. No se puede cancelar la asignación.")
    now = to_utc_naive(utc_now())
    await get_mensajeria_asignaciones_collection().update_one(
        {"_id": assignment["_id"]},
        {"$set": {"status": "cancelled", "updated_at": now}},
    )
    remaining = await get_mensajeria_asignaciones_collection().count_documents(
        {"batch_id": batch["_id"], "status": "assigned"}
    )
    if remaining == 0:
        await get_mensajeria_batches_collection().update_one(
            {"_id": batch["_id"]},
            {"$set": {"status": "cancelled", "updated_at": now}},
        )
    code = str(order_oid)[-6:].upper()
    await _push_mensajero(str(assignment["mensajero_id"]), "Asignación cancelada", f"La tienda retiró el pedido #{code}.")
    return {"cancelled": True, "order_id": order_id}


async def _batch_public(batch: dict | None) -> dict:
    if not batch:
        raise HTTPException(status_code=404, detail="No encontramos esa mensajería.")
    assignments = await get_mensajeria_asignaciones_collection().find({"batch_id": batch["_id"]}).to_list(length=100)
    orders = []
    for assignment in assignments:
        order = await get_orders_collection().find_one({"_id": assignment["order_id"]})
        if not order:
            continue
        brief = _order_brief(order)
        brief.update({
            "assignment_status": assignment.get("status"),
            "pay_via": assignment.get("pay_via"),
            "fee_amount": assignment.get("fee_amount"),
            "fee_currency": assignment.get("fee_currency"),
            "evidence": assignment.get("evidence"),
            "qvapay_paid": bool(assignment.get("qvapay_transfer_id")),
        })
        orders.append(brief)
    points = await get_mensajeria_puntos_collection().find({"batch_id": batch["_id"]}).sort("recorded_at", ASCENDING).to_list(length=2000)
    return {
        "id": str(batch["_id"]),
        "status": batch.get("status"),
        "vehicle_id": batch.get("vehicle_id"),
        "window_start": batch.get("window_start"),
        "window_end": batch.get("window_end"),
        "started_at": batch.get("started_at"),
        "closed_at": batch.get("closed_at"),
        "notice_read_at": batch.get("notice_read_at"),
        "orders": orders,
        "km": haversine_km(points),
        "points": [{"lat": item["lat"], "lng": item["lng"]} for item in points],
    }


async def batches_for_messenger(mensajero_id: str) -> list[dict]:
    docs = await get_mensajeria_batches_collection().find(
        {"mensajero_id": _oid(mensajero_id, "Mensajero no encontrado."), "status": {"$ne": "cancelled"}}
    ).sort("window_start", ASCENDING).to_list(length=100)
    return [await _batch_public(doc) for doc in docs]


async def summary_for_messenger(mensajero_id: str, *, start: datetime | None, end: datetime | None) -> dict:
    batches = await batches_for_messenger(mensajero_id)
    pending_count = 0
    pending_amounts: dict[str, float] = {}
    done_count = 0
    done_amounts: dict[str, float] = {}
    km = 0.0
    for batch in batches:
        window = batch.get("window_start")
        if start and window and to_utc_naive(window) < to_utc_naive(start):
            continue
        if end and window and to_utc_naive(window) > to_utc_naive(end):
            continue
        if batch["status"] == "completed":
            km += float(batch.get("km") or 0)
        for order in batch["orders"]:
            if order["assignment_status"] == "cancelled":
                continue
            currency = order.get("fee_currency") or "CUP"
            amount = float(order.get("fee_amount") or 0)
            if order["assignment_status"] != "closed":
                pending_count += 1
                pending_amounts[currency] = round(pending_amounts.get(currency, 0) + amount, 2)
                continue
            done_count += 1
            collected = order.get("pay_via") != "qvapay" or order.get("qvapay_paid")
            if collected:
                done_amounts[currency] = round(done_amounts.get(currency, 0) + amount, 2)
    return {
        "pending_count": pending_count,
        "pending_amounts": pending_amounts,
        "done_count": done_count,
        "done_amounts": done_amounts,
        "km": round(km, 2),
        "batches": batches,
    }


async def mark_notice_read(mensajero_id: str, batch_id: str) -> dict:
    messenger = await assert_mensajero_active(mensajero_id)
    batch = await get_mensajeria_batches_collection().find_one({
        "_id": _oid(batch_id, "Mensajería no encontrada."),
        "mensajero_id": messenger["_id"],
    })
    if not batch:
        raise HTTPException(status_code=404, detail="No encontramos esa mensajería.")
    now = to_utc_naive(utc_now())
    if not batch.get("notice_read_at"):
        await get_mensajeria_batches_collection().update_one(
            {"_id": batch["_id"]},
            {"$set": {"notice_read_at": now, "updated_at": now}},
        )
        batch["notice_read_at"] = now
    return await _batch_public(batch)


async def mark_started_orders_in_transit(order_ids: list) -> set:
    ids = [item for item in order_ids if item is not None]
    if not ids:
        return set()
    active = await get_mensajeria_asignaciones_collection().find(
        {"order_id": {"$in": ids}, "status": "in_route"},
        {"order_id": 1},
    ).to_list(length=len(ids))
    transit_ids = [item["order_id"] for item in active if item.get("order_id") is not None]
    if not transit_ids:
        return set()
    await get_orders_collection().update_many(
        {"_id": {"$in": transit_ids}, "status": "pending_confirmation"},
        {"$set": {"status": "in_transit", "updated_at": to_utc_naive(utc_now())}},
    )
    return set(transit_ids)


async def start_route(mensajero_id: str, batch_id: str, vehicle_id: str, client_id: str | None) -> dict:
    messenger = await assert_mensajero_active(mensajero_id)
    vehicle = next((item for item in messenger.get("vehicles") or [] if item.get("id") == vehicle_id), None)
    if not vehicle:
        raise HTTPException(status_code=422, detail="Elige un vehículo de tu perfil.")
    running = await get_mensajeria_batches_collection().find_one({
        "mensajero_id": messenger["_id"],
        "status": "in_progress",
    })
    batch = await get_mensajeria_batches_collection().find_one({
        "_id": _oid(batch_id, "Mensajería no encontrada."),
        "mensajero_id": messenger["_id"],
    })
    if not batch:
        raise HTTPException(status_code=404, detail="No encontramos esa mensajería.")
    if batch.get("status") == "in_progress":
        return await _batch_public(batch)
    if running and running["_id"] != batch["_id"]:
        raise HTTPException(status_code=409, detail="Ya tienes una ruta en curso.")
    if batch.get("status") != "assigned":
        raise HTTPException(status_code=409, detail="Esta mensajería no se puede iniciar.")
    now = to_utc_naive(utc_now())
    assigned = await get_mensajeria_asignaciones_collection().find(
        {"batch_id": batch["_id"], "status": "assigned"},
        {"order_id": 1},
    ).to_list(length=200)
    await get_mensajeria_batches_collection().update_one(
        {"_id": batch["_id"], "status": "assigned"},
        {"$set": {"status": "in_progress", "vehicle_id": vehicle_id, "started_at": now, "updated_at": now, "client_start_id": client_id}},
    )
    await get_mensajeria_asignaciones_collection().update_many(
        {"batch_id": batch["_id"], "status": "assigned"},
        {"$set": {"status": "in_route", "updated_at": now}},
    )
    order_ids = [item["order_id"] for item in assigned if item.get("order_id")]
    if order_ids:
        await get_orders_collection().update_many(
            {"_id": {"$in": order_ids}, "status": "pending_confirmation"},
            {"$set": {"status": "in_transit", "updated_at": now}},
        )
    batch["status"] = "in_progress"
    public = await _batch_public(batch)
    seller_id = str(batch["seller_id"])
    await publish_seller_data_update(seller_id, "orders")
    await notify_seller_notice(
        seller_id,
        title="Mensajería en camino",
        content="El mensajero comenzó la ruta de los pedidos asignados.",
        kind="courier_route",
    )
    seen: set[str] = set()
    for order in public["orders"]:
        full = await get_orders_collection().find_one({"_id": _oid(order["id"], "Pedido no encontrado.")})
        buyer_id = str((full or {}).get("buyer_id") or "")
        if not buyer_id or buyer_id in seen:
            continue
        seen.add(buyer_id)
        await publish_customer_notification(buyer_id, {
            "id": f"route-{batch['_id']}-{buyer_id}",
            "title": "Tu pedido va en camino",
            "content": "El mensajero comenzó la ruta.",
            "kind": "courier_route",
            "order_id": order["id"],
        })
    return public


async def add_point(mensajero_id: str, batch_id: str, point) -> dict:
    batch = await get_mensajeria_batches_collection().find_one({
        "_id": _oid(batch_id, "Mensajería no encontrada."),
        "mensajero_id": _oid(mensajero_id, "Mensajero no encontrado."),
        "status": "in_progress",
    })
    if not batch:
        raise HTTPException(status_code=409, detail="No hay una ruta en curso.")
    now = to_utc_naive(point.recorded_at or utc_now())
    document = {
        "client_id": point.client_id,
        "batch_id": batch["_id"],
        "mensajero_id": batch["mensajero_id"],
        "lat": point.lat,
        "lng": point.lng,
        "accuracy": point.accuracy,
        "recorded_at": now,
    }
    try:
        await get_mensajeria_puntos_collection().insert_one(document)
    except DuplicateKeyError:
        return {"stored": True, "duplicate": True}
    payload = {"type": "courier_location", "batch_id": str(batch["_id"]), "lat": point.lat, "lng": point.lng, "recorded_at": now.isoformat()}
    await hub.send(str(batch["seller_id"]), payload)
    assignments = await get_mensajeria_asignaciones_collection().find(
        {"batch_id": batch["_id"], "status": "in_route"}
    ).to_list(length=100)
    for assignment in assignments:
        order = await get_orders_collection().find_one({"_id": assignment["order_id"]}, {"buyer_id": 1})
        if order and order.get("buyer_id"):
            await customer_hub.send(str(order["buyer_id"]), {**payload, "order_id": str(order["_id"])})
    return {"stored": True}


async def courier_evidence_pdf(order_id: str, *, seller_id: str | None = None, mensajero_id: str | None = None) -> tuple[bytes, str]:
    query: dict[str, Any] = {
        "order_id": _oid(order_id, "Pedido no encontrado."),
        "status": {"$ne": "cancelled"},
    }
    if seller_id:
        query["seller_id"] = _oid(seller_id, "Tienda no encontrada.")
    if mensajero_id:
        query["mensajero_id"] = _oid(mensajero_id, "Mensajero no encontrado.")
    assignment = await get_mensajeria_asignaciones_collection().find_one(query, sort=[("created_at", DESCENDING)])
    if not assignment:
        raise HTTPException(status_code=404, detail="Ese pedido no está en tu mensajería.")
    evidence = assignment.get("evidence") if isinstance(assignment.get("evidence"), dict) else None
    images = [str(url) for url in ((evidence or {}).get("images") or []) if url]
    note = str((evidence or {}).get("note") or "").strip()
    if not evidence or (not note and not images):
        raise HTTPException(status_code=404, detail="Este pedido no tiene evidencia del mensajero.")
    order = await get_orders_collection().find_one({"_id": assignment["order_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    messenger = await get_mensajeros_collection().find_one(
        {"_id": assignment["mensajero_id"]},
        {"first_name": 1, "last_name": 1},
    )
    seller = await get_registrations_collection().find_one({"_id": assignment["seller_id"]}, {"store_name": 1})
    delivery = order.get("delivery") or {}
    messenger_name = " ".join(
        part for part in (
            str((messenger or {}).get("first_name") or "").strip(),
            str((messenger or {}).get("last_name") or "").strip(),
        ) if part
    )
    import asyncio
    from app.payments.dispute_report import build_courier_evidence_pdf

    payload = {
        "code": str(order["_id"])[-6:].upper(),
        "store_name": str((seller or {}).get("store_name") or ""),
        "buyer_name": order.get("buyer_name") or delivery.get("recipient_name") or "Cliente",
        "address": delivery.get("address") or "",
        "messenger_name": messenger_name,
        "note": note,
        "images": images,
        "submitted_at": evidence.get("submitted_at"),
    }
    return await asyncio.to_thread(build_courier_evidence_pdf, payload)


async def submit_evidence(mensajero_id: str, order_id: str, *, note: str, image_urls: list[str], client_id: str | None) -> dict:
    assignment = await get_mensajeria_asignaciones_collection().find_one({
        "order_id": _oid(order_id, "Pedido no encontrado."),
        "mensajero_id": _oid(mensajero_id, "Mensajero no encontrado."),
        "status": {"$in": ["assigned", "in_route", "closed"]},
    })
    if not assignment or assignment.get("status") == "cancelled":
        raise HTTPException(status_code=404, detail="Ese pedido no está en tu ruta.")
    if client_id and (assignment.get("evidence") or {}).get("client_id") == client_id:
        return {"closed": True, "duplicate": True}
    finishing = assignment.get("status") != "closed"
    now = to_utc_naive(utc_now())
    evidence = {"client_id": client_id, "note": note.strip(), "images": image_urls, "submitted_at": now}
    await get_mensajeria_asignaciones_collection().update_one(
        {"_id": assignment["_id"]},
        {"$set": {"status": "closed", "evidence": evidence, "updated_at": now}},
    )
    await get_orders_collection().update_one(
        {"_id": assignment["order_id"], "status": {"$ne": "cancelled"}},
        {"$set": {"status": "completed", "completed_at": now, "updated_at": now}},
    )
    open_left = await get_mensajeria_asignaciones_collection().count_documents(
        {"batch_id": assignment["batch_id"], "status": {"$in": list(ACTIVE_ASSIGNMENT)}}
    )
    if open_left == 0:
        await get_mensajeria_batches_collection().update_one(
            {"_id": assignment["batch_id"], "status": {"$ne": "cancelled"}},
            {"$set": {"status": "completed", "closed_at": now, "updated_at": now}},
        )
    code = str(assignment["order_id"])[-6:].upper()
    if finishing:
        await notify_seller_notice(
            assignment["seller_id"],
            title="Pedido entregado",
            content=f"El mensajero entregó el pedido #{code}.",
            kind="courier_evidence",
            order_id=str(assignment["order_id"]),
        )
        order = await get_orders_collection().find_one({"_id": assignment["order_id"]}, {"buyer_id": 1})
        buyer_id = str((order or {}).get("buyer_id") or "")
        if buyer_id:
            from app.payments.service import _notify_customer
            await _notify_customer(
                buyer_id,
                str(assignment["order_id"]),
                "Pedido entregado",
                f"El mensajero entregó tu pedido #{code}.",
                "courier_delivered",
                sms=False,
            )
    return {"closed": True}


async def set_profile_photo(mensajero_id: str, url: str) -> dict:
    doc = await assert_mensajero_active(mensajero_id)
    await get_mensajeros_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": {"profile_photo_url": url, "updated_at": to_utc_naive(utc_now())}},
    )
    doc["profile_photo_url"] = url
    return _public(doc)


def _vehicle_photo_urls(item: dict) -> list[str]:
    urls = [str(url) for url in (item.get("photo_urls") or []) if url]
    legacy = item.get("photo_url")
    if not urls and legacy:
        return [str(legacy)]
    return urls


def _require_vehicle_photos(urls: list[str]) -> list[str]:
    if not urls:
        raise HTTPException(status_code=422, detail="Sube al menos una foto del vehículo.")
    if len(urls) > 5:
        raise HTTPException(status_code=422, detail="Puedes subir hasta 5 fotos del vehículo.")
    return urls


async def add_vehicle(mensajero_id: str, vehicle_type: str, plate: str, photo_urls: list[str]) -> dict:
    if vehicle_type not in VEHICLE_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de vehículo no válido.")
    photos = _require_vehicle_photos(photo_urls)
    doc = await assert_mensajero_active(mensajero_id)
    vehicle = {
        "id": str(ObjectId()),
        "vehicle_type": vehicle_type,
        "plate": plate.strip(),
        "photo_url": photos[0],
        "photo_urls": photos,
    }
    await get_mensajeros_collection().update_one(
        {"_id": doc["_id"]},
        {"$push": {"vehicles": vehicle}, "$set": {"updated_at": to_utc_naive(utc_now())}},
    )
    doc.setdefault("vehicles", []).append(vehicle)
    return _public(doc)


async def update_vehicle(mensajero_id: str, vehicle_id: str, vehicle_type: str, plate: str, keep_urls: list[str], new_urls: list[str]) -> dict:
    if vehicle_type not in VEHICLE_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de vehículo no válido.")
    doc = await assert_mensajero_active(mensajero_id)
    current = next((item for item in doc.get("vehicles") or [] if item.get("id") == vehicle_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail="No encontramos ese vehículo.")
    owned = _vehicle_photo_urls(current)
    photos = _require_vehicle_photos([*[url for url in keep_urls if url in owned], *new_urls])
    current["vehicle_type"] = vehicle_type
    current["plate"] = plate.strip()
    current["photo_url"] = photos[0]
    current["photo_urls"] = photos
    await get_mensajeros_collection().update_one(
        {"_id": doc["_id"], "vehicles.id": vehicle_id},
        {"$set": {
            "vehicles.$.vehicle_type": current["vehicle_type"],
            "vehicles.$.plate": current["plate"],
            "vehicles.$.photo_url": photos[0],
            "vehicles.$.photo_urls": photos,
            "updated_at": to_utc_naive(utc_now()),
        }},
    )
    return _public(doc)


async def delete_vehicle(mensajero_id: str, vehicle_id: str) -> dict:
    doc = await assert_mensajero_active(mensajero_id)
    if not any(item.get("id") == vehicle_id for item in doc.get("vehicles") or []):
        raise HTTPException(status_code=404, detail="No encontramos ese vehículo.")
    busy = await get_mensajeria_batches_collection().find_one({
        "mensajero_id": doc["_id"],
        "vehicle_id": vehicle_id,
        "status": "in_progress",
    })
    if busy:
        raise HTTPException(status_code=409, detail="No se puede eliminar: está en una ruta.")
    await get_mensajeros_collection().update_one(
        {"_id": doc["_id"]},
        {"$pull": {"vehicles": {"id": vehicle_id}}, "$set": {"updated_at": to_utc_naive(utc_now())}},
    )
    doc["vehicles"] = [item for item in doc.get("vehicles") or [] if item.get("id") != vehicle_id]
    return _public(doc)


async def set_qvapay(mensajero_id: str, username: str, *, skip_verification_on_service_error: bool = False) -> dict:
    doc = await assert_mensajero_active(mensajero_id)
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Escribe tu usuario QvaPay.")
    verified = True
    try:
        normalized = await verify_qvapay_username(normalized)
    except HTTPException as exc:
        if not skip_verification_on_service_error or exc.status_code != 503:
            raise
        verified = False
    now = to_utc_naive(utc_now())
    update: dict[str, Any] = {"qvapay_username": normalized, "updated_at": now}
    mongo: dict[str, Any] = {"$set": update}
    if verified:
        update["qvapay_verified_at"] = now
    else:
        mongo["$unset"] = {"qvapay_verified_at": ""}
        doc["qvapay_verified_at"] = None
    await get_mensajeros_collection().update_one({"_id": doc["_id"]}, mongo)
    doc.update(update)
    return _public(doc)


async def delete_qvapay(mensajero_id: str) -> dict:
    doc = await assert_mensajero_active(mensajero_id)
    await get_mensajeros_collection().update_one(
        {"_id": doc["_id"]},
        {"$unset": {"qvapay_username": "", "qvapay_verified_at": ""}, "$set": {"updated_at": to_utc_naive(utc_now())}},
    )
    doc["qvapay_username"] = None
    doc["qvapay_verified_at"] = None
    return _public(doc)


async def save_customer_location(customer_id: str, order_id: str, lat: float, lng: float) -> dict:
    order = await get_orders_collection().find_one({"_id": _oid(order_id, "Pedido no encontrado."), "buyer_id": customer_id})
    if not order:
        order = await get_orders_collection().find_one({"_id": _oid(order_id, "Pedido no encontrado."), "buyer_id": _maybe_oid(customer_id)})
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    point = {"lat": lat, "lng": lng, "recorded_at": to_utc_naive(utc_now())}
    await get_orders_collection().update_one({"_id": order["_id"]}, {"$set": {"customer_location": point}})
    return point


def _maybe_oid(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return value


async def tracking_for(order_id: str, *, seller_id: str | None = None, customer_id: str | None = None) -> dict:
    order = await get_orders_collection().find_one({"_id": _oid(order_id, "Pedido no encontrado.")})
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if seller_id and str(order.get("seller_id")) != str(seller_id):
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if customer_id and str(order.get("buyer_id")) not in {str(customer_id), str(_maybe_oid(customer_id))}:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    assignment = await get_mensajeria_asignaciones_collection().find_one(
        {"order_id": order["_id"], "status": {"$ne": "cancelled"}},
        sort=[("created_at", DESCENDING)],
    )
    points = []
    messenger = None
    if assignment:
        points = await get_mensajeria_puntos_collection().find({"batch_id": assignment["batch_id"]}).sort("recorded_at", ASCENDING).to_list(length=2000)
        person = await get_mensajeros_collection().find_one({"_id": assignment.get("mensajero_id")})
        batch = await get_mensajeria_batches_collection().find_one({"_id": assignment["batch_id"]})
        if person:
            vehicles = person.get("vehicles") or []
            chosen = next((item for item in vehicles if item.get("id") == (batch or {}).get("vehicle_id")), None) or (vehicles[0] if vehicles else None)
            photos = _vehicle_photo_urls(chosen) if chosen else []
            messenger = {
                "first_name": person.get("first_name") or "",
                "last_name": person.get("last_name") or "",
                "profile_photo_url": person.get("profile_photo_url"),
                "vehicle_photo_urls": photos,
            }
    delivery = order.get("delivery") or {}
    latest = points[-1] if points else None
    buyer_oid = _maybe_oid(str(order.get("buyer_id") or ""))
    customer_photo = None
    if isinstance(buyer_oid, ObjectId):
        customer = await get_customers_collection().find_one({"_id": buyer_oid}, {"profile_photo_url": 1})
        customer_photo = (customer or {}).get("profile_photo_url")
    return {
        "points": [{"lat": item["lat"], "lng": item["lng"], "recorded_at": item.get("recorded_at")} for item in points],
        "destination": {
            "lat": delivery.get("latitude"),
            "lng": delivery.get("longitude"),
            "label": delivery.get("address") or "",
            "customer_photo_url": customer_photo,
        },
        "customer_location": order.get("customer_location"),
        "courier": None if latest is None else {"lat": latest["lat"], "lng": latest["lng"]},
        "messenger": messenger,
    }


async def _push_mensajero(mensajero_id: str, title: str, body: str) -> None:
    messenger = await get_mensajeros_collection().find_one({"_id": _oid(mensajero_id, "Mensajero no encontrado.")})
    tokens = await list_device_tokens(mensajero_id)
    await notify_device_tokens(
        tokens,
        title,
        body,
        data={"screen": "mensajero_panel", "alias": str((messenger or {}).get("username") or "")},
    )
