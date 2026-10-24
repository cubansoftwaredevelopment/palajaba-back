import uuid
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

from app.constants import REJECTION_REASON_UNCONFIRMED_PAYMENT
from app.database import get_registrations_collection
from app.auth.schemas import RegistrationPublic
from app.subscriptions.schemas import RegistrationSubscriptionReplace
from app.auth.utils import hash_password
from app.services.admin_registration_insights import (
    aggregate_product_counts_by_seller,
    aggregate_sales_cup_by_seller,
    build_marketplace_visibility_notes,
)
from app.subscriptions.service import normalize_billing_period, normalize_plan_tier
from app.subscriptions.service import expiry_notice_reset, expiry_notice_sent
from app.services.discount_codes import validate_discount_code
from app.services.seller_profile import ensure_store_name_available, is_profile_complete
from app.subscriptions.service import (
    record_subscription_payment,
    registration_id_str,
    upsert_latest_subscription_payment,
)
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug

PHONE_PREFIX = "+53"
TRIAL_DAYS = 15


def normalize_transfer_id(value: str) -> str:
    return value.strip()


def phone_display(digits: str) -> str:
    return f"{PHONE_PREFIX}{digits}"


def _legacy_timestamp(doc: dict[str, Any], *fields: str) -> datetime:
    """Solo para registros de prueba locales sin created_at/updated_at."""
    for field in fields:
        if field in doc:
            return to_utc_naive(doc[field])
    return to_utc_naive(utc_now())


def document_to_public(
    doc: dict[str, Any],
    *,
    product_counts: dict[str, int] | None = None,
    marketplace_visibility_notes: list[str] | None = None,
    sales_total_cup: float = 0,
) -> RegistrationPublic:
    counts = product_counts or {}
    notes = marketplace_visibility_notes
    if notes is None and doc.get("status") in ("approved", "expired"):
        notes = build_marketplace_visibility_notes(doc, counts)

    return RegistrationPublic(
        id=str(doc["_id"]),
        transfer_id=doc["transfer_id"],
        store_name=doc["store_name"],
        email=doc.get("email") or None,
        phone=phone_display(doc["phone"]),
        is_trial=bool(doc.get("is_trial")),
        billing_period=(
            normalize_billing_period(doc["billing_period"])
            if "billing_period" in doc
            else "monthly"
        ),
        plan_tier=normalize_plan_tier(doc.get("plan_tier")),
        status=doc["status"],
        subscription_starts_at=doc.get("subscription_starts_at"),
        subscription_ends_at=doc.get("subscription_ends_at"),
        expiry_notice_sms_sent=expiry_notice_sent(
            doc, "sms", doc.get("subscription_ends_at")
        ),
        rejection_reason=doc.get("rejection_reason"),
        created_at=(
            doc["created_at"]
            if "created_at" in doc
            else _legacy_timestamp(doc, "approved_at", "subscription_starts_at")
        ),
        updated_at=(
            doc["updated_at"]
            if "updated_at" in doc
            else _legacy_timestamp(doc, "created_at", "approved_at", "subscription_starts_at")
        ),
        approved_at=doc.get("approved_at"),
        payment_amount_cup=doc.get("payment_amount_cup"),
        discount_code=doc.get("discount_code"),
        discount_percent=doc.get("discount_percent"),
        expected_payment_cup=doc.get("expected_payment_cup"),
        is_launch_promo=bool(doc.get("is_launch_promo")),
        store_slug=doc.get("store_slug") or store_name_to_slug(doc["store_name"]),
        profile_completed=is_profile_complete(doc),
        total_product_count=int(counts.get("total") or 0),
        published_product_count=int(counts.get("published") or 0),
        view_only_product_count=int(counts.get("view_only") or 0),
        unavailable_product_count=int(counts.get("unavailable") or 0),
        marketplace_visibility_notes=notes or [],
        sales_total_cup=sales_total_cup,
    )


async def _registrations_to_public(documents: list[dict[str, Any]]) -> list[RegistrationPublic]:
    seller_ids = [str(doc["_id"]) for doc in documents]
    counts_by_seller = await aggregate_product_counts_by_seller(seller_ids)
    sales_by_seller = await aggregate_sales_cup_by_seller(seller_ids)
    return [
        document_to_public(
            doc,
            product_counts=counts_by_seller.get(str(doc["_id"])),
            marketplace_visibility_notes=build_marketplace_visibility_notes(
                doc,
                counts_by_seller.get(str(doc["_id"])),
            )
            if doc.get("status") in ("approved", "expired")
            else [],
            sales_total_cup=sales_by_seller.get(str(doc["_id"]), 0),
        )
        for doc in documents
    ]


async def _registration_to_public(doc: dict[str, Any]) -> RegistrationPublic:
    seller_id = str(doc["_id"])
    counts_by_seller = await aggregate_product_counts_by_seller([seller_id])
    sales_by_seller = await aggregate_sales_cup_by_seller([seller_id])
    counts = counts_by_seller.get(seller_id)
    return document_to_public(
        doc,
        product_counts=counts,
        marketplace_visibility_notes=build_marketplace_visibility_notes(doc, counts)
        if doc.get("status") in ("approved", "expired")
        else [],
        sales_total_cup=sales_by_seller.get(seller_id, 0),
    )


def normalize_email(value: str) -> str:
    return value.strip().lower()


def phone_e164(digits: str) -> str:
    return f"{PHONE_PREFIX}{digits}"


async def assert_contact_available(*, phone: str, email: str, store_name: str) -> None:
    collection = get_registrations_collection()
    existing_phone = await collection.find_one({"phone": phone})
    if existing_phone:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este número de teléfono ya está registrado.",
        )
    existing_email = await collection.find_one({"email": normalize_email(email)})
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este correo ya está registrado.",
        )
    await ensure_store_name_available(store_name)


def default_subscription_end(start: datetime, billing_period: str) -> datetime:
    from app.subscriptions.utils import subscription_period_end

    return subscription_period_end(start, billing_period)


async def create_registration(
    *,
    transfer_id: str | None,
    store_name: str,
    phone: str,
    email: str,
    password: str | None = None,
    password_hash: str | None = None,
    billing_period: str,
    plan_tier: str = "standard",
    discount_code: str | None = None,
    is_trial: bool = False,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    now = to_utc_naive(utc_now())
    normalized_email = normalize_email(email)

    if is_trial:
        normalized_transfer_id = f"TRIAL-{uuid.uuid4()}"
        billing_period = "monthly"
        plan_tier = "standard"
        discount_code = None
    else:
        if not transfer_id or not str(transfer_id).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El ID de la transferencia es obligatorio.",
            )
        normalized_transfer_id = normalize_transfer_id(transfer_id)
        existing_transfer = await collection.find_one(
            {"transfer_id": normalized_transfer_id}
        )
        if existing_transfer:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un registro con ese ID de transferencia.",
            )

    await assert_contact_available(phone=phone, email=normalized_email, store_name=store_name)

    if not password_hash and not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña es obligatoria.",
        )
    hashed = password_hash or hash_password(password)

    ends_at = now + timedelta(days=TRIAL_DAYS) if is_trial else None
    document = {
        "transfer_id": normalized_transfer_id,
        "store_name": store_name,
        "store_slug": store_name_to_slug(store_name),
        "email": normalized_email,
        "phone": phone,
        "password_hash": hashed,
        "billing_period": billing_period,
        "plan_tier": normalize_plan_tier(plan_tier),
        "is_trial": bool(is_trial),
        "status": "approved" if is_trial else "pending",
        "subscription_starts_at": now if is_trial else None,
        "subscription_ends_at": ends_at,
        **expiry_notice_reset(),
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "approved_at": now if is_trial else None,
        "payment_amount_cup": 0 if is_trial else None,
        "discount_code": None,
        "discount_percent": None,
        "expected_payment_cup": 0 if is_trial else None,
        "profile_photo_url": None,
        "business_location": None,
        "biography": None,
        "social_instagram": None,
        "social_facebook": None,
        "category_ids": [],
        "offers_delivery": None,
        "gestores_enabled": False,
        "profile_completed_at": None,
        "gestor_catalog_access": {
            "mode": "selected",
            "product_ids": [],
        },
        "checkout_gestor_ids": [],
        "checkout_include_store_phone": True,
    }

    if discount_code:
        validation = await validate_discount_code(
            discount_code,
            plan_tier=plan_tier,
            billing_period=billing_period,
        )
        document["discount_code"] = validation.code
        document["discount_percent"] = validation.percent_off
        document["expected_payment_cup"] = validation.discounted_amount_cup

    result = await collection.insert_one(document)
    document["_id"] = result.inserted_id
    return document_to_public(document)


async def sync_expired_registrations() -> None:
    """Pasa a «expired» las tiendas aprobadas cuya suscripción ya venció."""
    collection = get_registrations_collection()
    now = to_utc_naive(utc_now())
    await collection.update_many(
        {
            "status": "approved",
            "subscription_ends_at": {"$lte": now},
        },
        {"$set": {"status": "expired", "updated_at": now}},
    )


async def mark_registration_expired_if_needed(doc: dict[str, Any]) -> None:
    if doc.get("status") != "approved":
        return

    ends_at = doc.get("subscription_ends_at")
    if ends_at is None:
        return

    now = to_utc_naive(utc_now())
    if to_utc_naive(ends_at) > now:
        return

    collection = get_registrations_collection()
    await collection.update_one(
        {"_id": doc["_id"], "status": "approved"},
        {"$set": {"status": "expired", "updated_at": now}},
    )
    doc["status"] = "expired"


async def list_registrations(status_filter: str | None = None) -> list[RegistrationPublic]:
    await sync_expired_registrations()
    collection = get_registrations_collection()
    query: dict[str, Any] = {}
    if status_filter and status_filter != "all":
        query["status"] = status_filter

    cursor = collection.find(query).sort("created_at", -1)
    documents = await cursor.to_list(length=None)
    return await _registrations_to_public(documents)


async def get_registration(registration_id: str) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)
    return await _registration_to_public(doc)


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
        ends_at = default_subscription_end(
            now,
            normalize_billing_period(doc["billing_period"])
            if "billing_period" in doc
            else "monthly",
        )
    else:
        ends_at = to_utc_naive(ends_at)

    if ends_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de fin de suscripción debe ser futura.",
        )

    if payment_amount_cup < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto pagado no puede ser negativo.",
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
                **expiry_notice_reset(),
            }
        },
    )

    await record_subscription_payment(
        registration_id=registration_id_str(doc),
        amount_cup=payment_amount_cup,
        kind="approval",
        recorded_at=now,
        plan_tier=doc.get("plan_tier"),
        billing_period=doc.get("billing_period"),
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return await _registration_to_public(updated)


async def replace_subscription(
    registration_id: str,
    payload: RegistrationSubscriptionReplace,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)

    if doc["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede editar la suscripción de tiendas aprobadas.",
        )

    from app.services.gestores import apply_plan_gestor_keep_list
    from app.subscriptions.utils import build_subscription_replace_fields

    plan_tier = normalize_plan_tier(payload.plan_tier)
    billing_period = normalize_billing_period(payload.billing_period)
    await apply_plan_gestor_keep_list(
        registration_id,
        plan_tier,
        payload.keep_gestor_ids,
    )

    now = to_utc_naive(utc_now())
    updates: dict[str, Any] = {
        **build_subscription_replace_fields(
            now,
            plan_tier=plan_tier,
            billing_period=billing_period,
        ),
        "updated_at": now,
        **expiry_notice_reset(),
    }

    await collection.update_one({"_id": doc["_id"]}, {"$set": updates})

    updated = await collection.find_one({"_id": doc["_id"]})
    return await _registration_to_public(updated)


async def renew_registration(
    registration_id: str,
    subscription_ends_at: datetime | None,
    payment_amount_cup: int,
    *,
    plan_tier: str | None = None,
    billing_period: str | None = None,
    keep_gestor_ids: list[str] | None = None,
) -> RegistrationPublic:
    collection = get_registrations_collection()
    doc = await _get_document_or_404(collection, registration_id)

    if doc["status"] not in ("expired", "approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden renovar tiendas aprobadas o con suscripción vencida.",
        )

    now = to_utc_naive(utc_now())
    billing = billing_period or (
        normalize_billing_period(doc["billing_period"])
        if "billing_period" in doc
        else "monthly"
    )
    ends_at = subscription_ends_at
    if ends_at is None:
        ends_at = default_subscription_end(now, billing)
    else:
        ends_at = to_utc_naive(ends_at)

    if ends_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de fin de suscripción debe ser futura.",
        )

    if payment_amount_cup < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto pagado no puede ser negativo.",
        )

    next_tier = normalize_plan_tier(plan_tier if plan_tier is not None else doc.get("plan_tier"))
    from app.services.gestores import apply_plan_gestor_keep_list

    await apply_plan_gestor_keep_list(registration_id, next_tier, keep_gestor_ids)

    updates: dict[str, Any] = {
        "status": "approved",
        "subscription_starts_at": now,
        "subscription_ends_at": ends_at,
        "payment_amount_cup": payment_amount_cup,
        "approved_at": now,
        "rejection_reason": None,
        "updated_at": now,
        "is_trial": False,
        **expiry_notice_reset(),
    }
    if plan_tier is not None:
        updates["plan_tier"] = normalize_plan_tier(plan_tier)
    if billing_period is not None:
        if billing_period not in ("monthly", "quarterly", "yearly"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Periodo de facturación inválido.",
            )
        updates["billing_period"] = billing_period

    await collection.update_one({"_id": doc["_id"]}, {"$set": updates})

    await record_subscription_payment(
        registration_id=registration_id_str(doc),
        amount_cup=payment_amount_cup,
        kind="renewal",
        recorded_at=now,
        plan_tier=updates.get("plan_tier", doc.get("plan_tier")),
        billing_period=updates.get("billing_period", billing),
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return await _registration_to_public(updated)


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

    if payment_amount_cup < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto pagado no puede ser negativo.",
        )

    now = to_utc_naive(utc_now())
    updates: dict[str, Any] = {
        "payment_amount_cup": payment_amount_cup,
        "updated_at": now,
    }

    await collection.update_one(
        {"_id": doc["_id"]},
        {"$set": updates},
    )


    await upsert_latest_subscription_payment(
        registration_id=registration_id_str(doc),
        amount_cup=payment_amount_cup,
        fallback_recorded_at=doc.get("approved_at") or now,
        plan_tier=doc.get("plan_tier"),
        billing_period=doc.get("billing_period"),
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return await _registration_to_public(updated)


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
    return await _registration_to_public(updated)


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
    await collection.create_index("email", unique=True, sparse=True)
    await collection.create_index("status")
    await collection.create_index("created_at")
    await collection.create_index("store_name")
    await collection.create_index("store_slug", unique=True)
    await collection.create_index("approved_at")
    await collection.create_index("is_launch_promo")
    await collection.update_many(
        {"plan_tier": {"$exists": False}},
        {"$set": {"plan_tier": "standard"}},
    )
    await collection.update_many(
        {},
        {
            "$unset": {
                "free_trial_used": "",
                "has_used_free_trial": "",
                "used_free_trial": "",
                "is_free_trial": "",
            }
        },
    )
