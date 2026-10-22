from datetime import timedelta

from bson import ObjectId
from fastapi import HTTPException, status

from app.database import (
    get_registrations_collection,
    get_seller_contact_otp_challenges_collection,
)
from app.register.otp import OTP_EXPIRES_IN_SECONDS, send_otp, verify_otp
from app.schemas.seller_profile import (
    SellerContactOtpStartResponse,
    SellerEmailUpdate,
    SellerPhoneUpdate,
)
from app.services.registrations import phone_e164
from app.services.seller_profile import (
    update_seller_email,
    update_seller_phone,
)
from app.utils.datetime import to_utc_naive, utc_now

KIND_PHONE = "phone"
KIND_EMAIL = "email"


def _challenge_object_id(challenge_id: str) -> ObjectId:
    try:
        return ObjectId(challenge_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a pedir el código.",
        ) from exc


async def ensure_seller_contact_otp_indexes() -> None:
    collection = get_seller_contact_otp_challenges_collection()
    await collection.create_index("expires_at", expireAfterSeconds=0)
    await collection.create_index([("seller_id", 1), ("kind", 1)])


async def _get_challenge(*, challenge_id: str, seller_id: str) -> dict:
    collection = get_seller_contact_otp_challenges_collection()
    doc = await collection.find_one(
        {
            "_id": _challenge_object_id(challenge_id),
            "seller_id": seller_id,
        }
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a pedir el código.",
        )
    expires_at = doc.get("expires_at")
    if expires_at and to_utc_naive(expires_at) <= to_utc_naive(utc_now()):
        await collection.delete_one({"_id": doc["_id"]})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a pedir el código.",
        )
    return doc


async def _save_challenge(*, seller_id: str, kind: str, target: dict, sent) -> SellerContactOtpStartResponse:
    now = to_utc_naive(utc_now())
    collection = get_seller_contact_otp_challenges_collection()
    await collection.delete_many({"seller_id": seller_id, "kind": kind})
    document = {
        "seller_id": seller_id,
        "kind": kind,
        "otp_hash": sent.hash,
        "created_at": now,
        "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS),
        **target,
    }
    result = await collection.insert_one(document)
    return SellerContactOtpStartResponse(
        challenge_id=str(result.inserted_id),
        expires_at=sent.expires_at,
        message=(
            "Te enviamos un código por SMS al nuevo número."
            if kind == KIND_PHONE
            else "Te enviamos un código a tu nuevo correo."
        ),
    )


async def start_phone_change(*, seller_id: str, phone: str) -> SellerContactOtpStartResponse:
    from app.services.seller_profile import _get_seller_doc

    doc = await _get_seller_doc(seller_id)
    if phone == doc.get("phone"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese ya es tu número de teléfono.",
        )
    existing = await get_registrations_collection().find_one(
        {"phone": phone, "_id": {"$ne": doc["_id"]}}
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese número ya está registrado en otra tienda.",
        )
    sent = await send_otp(phone_e164=phone_e164(phone))
    return await _save_challenge(
        seller_id=seller_id,
        kind=KIND_PHONE,
        target={"phone": phone},
        sent=sent,
    )


async def start_email_change(*, seller_id: str, email: str) -> SellerContactOtpStartResponse:
    from app.services.seller_profile import _get_seller_doc

    doc = await _get_seller_doc(seller_id)
    current_email = (doc.get("email") or "").strip().lower()
    if email == current_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese ya es tu correo electrónico.",
        )
    existing = await get_registrations_collection().find_one(
        {"email": email, "_id": {"$ne": doc["_id"]}}
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este correo ya está registrado.",
        )
    sent = await send_otp(email=email)
    return await _save_challenge(
        seller_id=seller_id,
        kind=KIND_EMAIL,
        target={"email": email},
        sent=sent,
    )


async def resend_contact_change(*, seller_id: str, challenge_id: str) -> SellerContactOtpStartResponse:
    doc = await _get_challenge(challenge_id=challenge_id, seller_id=seller_id)
    kind = doc.get("kind")
    if kind == KIND_PHONE:
        sent = await send_otp(phone_e164=phone_e164(doc["phone"]))
    elif kind == KIND_EMAIL:
        sent = await send_otp(email=doc["email"])
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pudimos reenviar el código.",
        )

    now = to_utc_naive(utc_now())
    await get_seller_contact_otp_challenges_collection().update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "otp_hash": sent.hash,
                "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS),
            }
        },
    )
    return SellerContactOtpStartResponse(
        challenge_id=challenge_id,
        expires_at=sent.expires_at,
        message="Código reenviado.",
    )


async def confirm_contact_change(*, seller_id: str, challenge_id: str, code: str):
    doc = await _get_challenge(challenge_id=challenge_id, seller_id=seller_id)
    await verify_otp(otp_hash=doc.get("otp_hash") or "", code=code)

    kind = doc.get("kind")
    if kind == KIND_PHONE:
        updated = await update_seller_phone(seller_id, SellerPhoneUpdate(phone=doc["phone"]))
    elif kind == KIND_EMAIL:
        updated = await update_seller_email(seller_id, SellerEmailUpdate(email=doc["email"]))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pudimos completar el cambio.",
        )

    await get_seller_contact_otp_challenges_collection().delete_one({"_id": doc["_id"]})
    return updated
