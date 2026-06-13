from __future__ import annotations

import logging
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument

from app.constants import LAUNCH_PROMO_LIMIT
from app.database import get_platform_settings_collection, get_registrations_collection
from app.schemas.launch_promo import LaunchPromoStatusPublic
from app.schemas.registration import RegistrationPublic
from app.security import hash_password
from app.services.plans import PREMIUM_PLAN_TIER
from app.services.registrations import default_subscription_end, document_to_public
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug

logger = logging.getLogger(__name__)

LAUNCH_PROMO_STATE_ID = "launch_promo"
LAUNCH_PROMO_TRANSFER_PREFIX = "LANZAMIENTO-"


async def count_launch_promo_claims() -> int:
    return await get_registrations_collection().count_documents({"is_launch_promo": True})


async def ensure_launch_promo_state() -> None:
    collection = get_platform_settings_collection()
    claimed = await count_launch_promo_claims()
    await collection.update_one(
        {"_id": LAUNCH_PROMO_STATE_ID},
        {
            "$set": {
                "claimed_count": claimed,
                "limit": LAUNCH_PROMO_LIMIT,
            },
            "$setOnInsert": {
                "created_at": to_utc_naive(utc_now()),
            },
        },
        upsert=True,
    )


def build_launch_promo_status(claimed_count: int) -> LaunchPromoStatusPublic:
    remaining = max(LAUNCH_PROMO_LIMIT - claimed_count, 0)
    return LaunchPromoStatusPublic(
        available=remaining > 0,
        limit=LAUNCH_PROMO_LIMIT,
        claimed_count=claimed_count,
        slots_remaining=remaining,
    )


async def get_launch_promo_status() -> LaunchPromoStatusPublic:
    claimed = await count_launch_promo_claims()
    return build_launch_promo_status(claimed)


async def _claim_launch_promo_slot() -> bool:
    await ensure_launch_promo_state()
    collection = get_platform_settings_collection()
    result = await collection.find_one_and_update(
        {
            "_id": LAUNCH_PROMO_STATE_ID,
            "claimed_count": {"$lt": LAUNCH_PROMO_LIMIT},
        },
        {
            "$inc": {"claimed_count": 1},
            "$set": {"limit": LAUNCH_PROMO_LIMIT, "updated_at": to_utc_naive(utc_now())},
        },
        return_document=ReturnDocument.AFTER,
    )
    return result is not None


async def _release_launch_promo_slot() -> None:
    collection = get_platform_settings_collection()
    await collection.update_one(
        {"_id": LAUNCH_PROMO_STATE_ID, "claimed_count": {"$gt": 0}},
        {
            "$inc": {"claimed_count": -1},
            "$set": {"updated_at": to_utc_naive(utc_now())},
        },
    )


async def create_launch_promo_registration(
    *,
    store_name: str,
    phone: str,
    password: str,
) -> RegistrationPublic:
    slot_claimed = await _claim_launch_promo_slot()
    if not slot_claimed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La promoción de lanzamiento ya no está disponible.",
        )

    collection = get_registrations_collection()
    now = to_utc_naive(utc_now())

    try:
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

        ends_at = default_subscription_end(now, "monthly")
        transfer_id = f"{LAUNCH_PROMO_TRANSFER_PREFIX}{ObjectId()}"

        document: dict[str, Any] = {
            "transfer_id": transfer_id,
            "store_name": store_name,
            "store_slug": store_name_to_slug(store_name),
            "phone": phone,
            "password_hash": hash_password(password),
            "billing_period": "monthly",
            "plan_tier": PREMIUM_PLAN_TIER,
            "status": "approved",
            "subscription_starts_at": now,
            "subscription_ends_at": ends_at,
            "rejection_reason": None,
            "created_at": now,
            "updated_at": now,
            "approved_at": now,
            "payment_amount_cup": 0,
            "is_launch_promo": True,
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
        logger.info("Registro promo lanzamiento creado: %s (%s)", store_name, result.inserted_id)
        return document_to_public(document)
    except HTTPException:
        await _release_launch_promo_slot()
        raise
    except Exception:
        await _release_launch_promo_slot()
        logger.exception("Error creando registro promo lanzamiento")
        raise
