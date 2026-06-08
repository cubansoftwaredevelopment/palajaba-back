from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.constants import REJECTION_REASON_UNCONFIRMED_PAYMENT
from app.database import get_registrations_collection
from app.schemas.registration import RegistrationPublic
from app.security import hash_password
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug

PHONE_PREFIX = "+53"


def normalize_transfer_id(value: str) -> str:
    return value.strip()


def phone_display(digits: str) -> str:
    return f"{PHONE_PREFIX}{digits}"


def document_to_public(doc: dict[str, Any]) -> RegistrationPublic:
    return RegistrationPublic(
        id=str(doc["_id"]),
        transfer_id=doc["transfer_id"],
        store_name=doc["store_name"],
        phone=phone_display(doc["phone"]),
        billing_period=doc["billing_period"],
        status=doc["status"],
        subscription_starts_at=doc.get("subscription_starts_at"),
        subscription_ends_at=doc.get("subscription_ends_at"),
        rejection_reason=doc.get("rejection_reason"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        approved_at=doc.get("approved_at"),
        payment_amount_cup=doc.get("payment_amount_cup"),
    )


def default_subscription_end(start: datetime, billing_period: str) -> datetime:
    if billing_period == "yearly":
        return start + timedelta(days=365)
    return start + timedelta(days=30)


async def create_registration(
    *,
    transfer_id: str,
    store_name: str,
    phone: str,
    password: str,
    billing_period: str,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    normalized_transfer_id = normalize_transfer_id(transfer_id)
    now = to_utc_naive(utc_now())

    existing_transfer = await collection.find_one(
        {"transfer_id": normalized_transfer_id}
    )
    if existing_transfer:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un registro con ese ID de transferencia.",
        )

    existing_phone = await collection.find_one({"phone": phone})
    if existing_phone:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este número de teléfono ya está registrado.",
        )

    existing_store = await collection.find_one(
        {"store_name": {"$regex": f"^{store_name}$", "$options": "i"}}
    )
    if existing_store:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una tienda con ese nombre.",
        )

    document = {
        "transfer_id": normalized_transfer_id,
        "store_name": store_name,
        "store_slug": store_name_to_slug(store_name),
        "phone": phone,
        "password_hash": hash_password(password),
        "billing_period": billing_period,
        "status": "pending",
        "subscription_starts_at": None,
        "subscription_ends_at": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "approved_at": None,
        "payment_amount_cup": None,
        "profile_photo_url": None,
        "business_location": None,
        "biography": None,
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": [],
        "offers_delivery": None,
        "profile_completed_at": None,
    }

    result = await collection.insert_one(document)
    document["_id"] = result.inserted_id
    return document_to_public(document)


async def list_registrations(status_filter: str | None = None) -> list[RegistrationPublic]:
    collection = get_registrations_collection()
    query: dict[str, Any] = {}
    if status_filter and status_filter != "all":
        query["status"] = status_filter

    cursor = collection.find(query).sort("created_at", -1)
    documents = await cursor.to_list(length=500)
    return [document_to_public(doc) for doc in documents]


async def get_registration(registration_id: str) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)
    return document_to_public(doc)


async def approve_registration(
    registration_id: str,
    subscription_ends_at: datetime | None,
    payment_amount_cup: int,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)

    if doc["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden aprobar solicitudes pendientes.",
        )

    now = to_utc_naive(utc_now())
    ends_at = subscription_ends_at
    if ends_at is None:
        ends_at = default_subscription_end(now, doc["billing_period"])
    else:
        ends_at = to_utc_naive(ends_at)

    if ends_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de fin de suscripción debe ser futura.",
        )

    if payment_amount_cup < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto pagado debe ser mayor que cero.",
        )

    await collection.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "status": "approved",
                "subscription_starts_at": now,
                "subscription_ends_at": ends_at,
                "rejection_reason": None,
                "approved_at": now,
                "payment_amount_cup": payment_amount_cup,
                "updated_at": now,
            }
        },
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_public(updated)


async def update_subscription_end(
    registration_id: str,
    subscription_ends_at: datetime,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)

    if doc["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede editar la suscripción de tiendas aprobadas.",
        )

    now = to_utc_naive(utc_now())
    ends_at = to_utc_naive(subscription_ends_at)

    if ends_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de fin de suscripción debe ser futura.",
        )

    await collection.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "subscription_ends_at": ends_at,
                "updated_at": now,
            }
        },
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_public(updated)


async def update_payment_amount(
    registration_id: str,
    payment_amount_cup: int,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)

    if doc["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede registrar el pago de tiendas aprobadas.",
        )

    if payment_amount_cup < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto pagado debe ser mayor que cero.",
        )

    now = to_utc_naive(utc_now())
    await collection.update_one(
        {"_id": doc["_id"]},
        {"$set": {"payment_amount_cup": payment_amount_cup, "updated_at": now}},
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_public(updated)


async def reject_registration(
    registration_id: str,
    reason: str | None = None,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)

    if doc["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden rechazar solicitudes pendientes.",
        )

    now = to_utc_naive(utc_now())
    rejection_reason = reason or REJECTION_REASON_UNCONFIRMED_PAYMENT
    await collection.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "status": "rejected",
                "rejection_reason": rejection_reason,
                "subscription_starts_at": None,
                "subscription_ends_at": None,
                "approved_at": None,
                "payment_amount_cup": None,
                "updated_at": now,
            }
        },
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_public(updated)


async def _get_document_or_404(collection, registration_id: str) -> dict[str, Any]:
    try:
        object_id = ObjectId(registration_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada.",
        ) from exc

    doc = await collection.find_one({"_id": object_id})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada.",
        )
    return doc


async def ensure_registration_indexes() -> None:
    collection = get_registrations_collection()
    cursor = collection.find({})
    async for doc in cursor:
        store_name = doc.get("store_name") or ""
        slug = store_name_to_slug(store_name)
        if doc.get("store_slug") != slug:
            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"store_slug": slug}},
            )

    await collection.create_index("transfer_id", unique=True)
    await collection.create_index("phone", unique=True)
    await collection.create_index("status")
    await collection.create_index("created_at")
    await collection.create_index("store_name")
    await collection.create_index("store_slug", unique=True)
    await collection.create_index("approved_at")
