"""Datos, OTP simulado y consultas del e2e de registro, login y recuperación."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from bson import ObjectId
from fastapi import HTTPException, status

from app.auth.utils import hash_password
from app.notifications.otp_manager import OtpSendResult
from app.database import (
    get_password_reset_challenges_collection,
    get_registration_otp_challenges_collection,
    get_registration_otp_sms_cooldowns_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.database import run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "auth_e2e_v1"
PASSWORD = "clave123"
EMAIL_CODE = "111111"
PHONE_CODE = "222222"
EMAIL_HASH = "auth-e2e-email-hash"
PHONE_HASH = "auth-e2e-phone-hash"


def store_name(seller_id: str) -> str:
    return f"TEST Auth {seller_id}"


def unique_phone(seed: ObjectId) -> str:
    return f"{(int(str(seed), 16) % 90000000) + 10000000:08d}"


def unique_email(seller_id: str) -> str:
    return f"tienda.{seller_id}@auth-e2e.test"


def seller_document(
    *,
    seller_id: ObjectId,
    status: str = "approved",
    subscription_days: int = 20,
) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "_id": seller_id,
        "status": status,
        "store_name": store_name(str(seller_id)),
        "store_slug": f"test-auth-{seller_id}",
        "transfer_id": f"TEST-AUTH-{seller_id}",
        "phone": unique_phone(seller_id),
        "email": unique_email(str(seller_id)),
        "password_hash": hash_password(PASSWORD),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "is_trial": False,
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["otros"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=subscription_days),
        "created_at": now,
        "updated_at": now,
        "auth_e2e_marker": MARKER,
    }


async def cleanup() -> None:
    registrations = get_registrations_collection()
    emails = [
        doc.get("email")
        async for doc in registrations.find({"auth_e2e_marker": MARKER}, {"email": 1})
    ]
    emails = [email for email in emails if email]
    await get_registration_otp_challenges_collection().delete_many(
        {"$or": [{"email": {"$regex": "@auth-e2e\\.test$"}}, {"store_name": {"$regex": "^TEST Auth "}}]}
    )
    await get_password_reset_challenges_collection().delete_many(
        {"email": {"$regex": "@auth-e2e\\.test$"}}
    )
    if emails:
        await get_password_reset_challenges_collection().delete_many({"email": {"$in": emails}})
    await get_registration_otp_sms_cooldowns_collection().delete_many({})
    await registrations.delete_many(
        {"$or": [{"auth_e2e_marker": MARKER}, {"email": {"$regex": "@auth-e2e\\.test$"}}]}
    )


def cleanup_db() -> None:
    run_db(cleanup)


async def _seed_seller(*, status: str = "approved", subscription_days: int = 20) -> dict:
    seller_id = ObjectId()
    doc = seller_document(seller_id=seller_id, status=status, subscription_days=subscription_days)
    await get_registrations_collection().insert_one(doc)
    return {
        "seller_id": str(seller_id),
        "store_name": doc["store_name"],
        "phone": doc["phone"],
        "email": doc["email"],
        "password": PASSWORD,
    }


def seed_seller(*, status: str = "approved", subscription_days: int = 20) -> dict:
    return run_db(lambda: _seed_seller(status=status, subscription_days=subscription_days))


async def fake_send_otp(*, email: str | None = None, phone_e164: str | None = None) -> OtpSendResult:
    if email:
        return OtpSendResult(hash=EMAIL_HASH, expires_at=None)
    if phone_e164:
        return OtpSendResult(hash=PHONE_HASH, expires_at=None)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Indica un correo o un teléfono para enviar el código.",
    )


async def fake_verify_otp(*, otp_hash: str, code: str) -> None:
    expected = EMAIL_CODE if otp_hash == EMAIL_HASH else PHONE_CODE
    if code.strip() != expected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El código no es válido.")


def patch_otp():
    return patch.multiple(
        "app.auth.service",
        send_otp=fake_send_otp,
        verify_otp=fake_verify_otp,
    )
