from datetime import timedelta

from bson import ObjectId
from fastapi import HTTPException, status

from app.database import get_password_reset_challenges_collection, get_registrations_collection
from app.register.otp import OTP_EXPIRES_IN_SECONDS, send_otp, verify_otp
from app.password_reset.schemas import (
    PasswordResetCompleteResponse,
    PasswordResetConfirmResponse,
    PasswordResetStartResponse,
)
from app.security import hash_password
from app.services.registrations import phone_e164
from app.utils.datetime import to_utc_naive, utc_now

CHALLENGE_TTL_SECONDS = OTP_EXPIRES_IN_SECONDS
ACCOUNT_NOT_FOUND = "No encontramos una cuenta con esos datos."


def mask_email(email: str) -> str:
    value = (email or "").strip()
    local, sep, domain = value.partition("@")
    if not sep or not domain:
        return "***"
    if len(local) <= 2:
        shown = f"{local[:1]}***"
    else:
        shown = f"{local[0]}***{local[-1]}"
    return f"{shown}@{domain}"


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())[-8:]
    if len(digits) < 8:
        return "***"
    return f"{digits[:2]}****{digits[-2:]}"


def _challenge_object_id(challenge_id: str) -> ObjectId:
    try:
        return ObjectId(challenge_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a solicitar los códigos.",
        ) from exc


async def ensure_password_reset_indexes() -> None:
    collection = get_password_reset_challenges_collection()
    await collection.create_index("expires_at", expireAfterSeconds=0)
    await collection.create_index("seller_id")


async def _get_challenge(challenge_id: str) -> dict:
    collection = get_password_reset_challenges_collection()
    doc = await collection.find_one({"_id": _challenge_object_id(challenge_id)})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a solicitar los códigos.",
        )
    expires_at = doc.get("expires_at")
    if expires_at and to_utc_naive(expires_at) <= to_utc_naive(utc_now()):
        await collection.delete_one({"_id": doc["_id"]})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a solicitar los códigos.",
        )
    return doc


def _start_response(doc: dict, *, message: str) -> PasswordResetStartResponse:
    return PasswordResetStartResponse(
        challenge_id=str(doc["_id"]),
        email_hint=mask_email(doc.get("email") or ""),
        phone_hint=mask_phone(doc.get("phone") or ""),
        email_expires_at=doc.get("email_expires_at"),
        phone_expires_at=doc.get("phone_expires_at"),
        message=message,
    )


async def _find_seller(*, method: str, phone: str | None, store_name: str | None) -> dict:
    collection = get_registrations_collection()
    if method == "phone":
        doc = await collection.find_one({"phone": phone})
    else:
        doc = await collection.find_one(
            {"store_name": {"$regex": f"^{store_name}$", "$options": "i"}}
        )
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ACCOUNT_NOT_FOUND)
    if doc.get("status") == "rejected":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ACCOUNT_NOT_FOUND)
    email = str(doc.get("email") or "").strip()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta cuenta no tiene correo. Escríbenos para recuperar el acceso.",
        )
    return doc


async def start_password_reset(
    *,
    method: str,
    phone: str | None = None,
    store_name: str | None = None,
) -> PasswordResetStartResponse:
    seller = await _find_seller(method=method, phone=phone, store_name=store_name)
    now = to_utc_naive(utc_now())
    collection = get_password_reset_challenges_collection()
    await collection.delete_many({"seller_id": str(seller["_id"])})

    phone_result = await send_otp(phone_e164=phone_e164(seller["phone"]))
    email_result = await send_otp(email=str(seller["email"]).strip())
    document = {
        "seller_id": str(seller["_id"]),
        "email": str(seller["email"]).strip(),
        "phone": seller["phone"],
        "email_hash": email_result.hash,
        "phone_hash": phone_result.hash,
        "email_verified": False,
        "phone_verified": False,
        "email_expires_at": email_result.expires_at,
        "phone_expires_at": phone_result.expires_at,
        "created_at": now,
        "expires_at": now + timedelta(seconds=CHALLENGE_TTL_SECONDS),
    }
    result = await collection.insert_one(document)
    document["_id"] = result.inserted_id
    return _start_response(
        document,
        message="Te enviamos un código al correo y otro por SMS de la cuenta.",
    )


async def resend_password_reset_otp(*, challenge_id: str, channel: str) -> PasswordResetStartResponse:
    doc = await _get_challenge(challenge_id)
    collection = get_password_reset_challenges_collection()
    updates: dict = {}
    email_expires_at = doc.get("email_expires_at")
    phone_expires_at = doc.get("phone_expires_at")

    if channel == "email":
        sent = await send_otp(email=doc["email"])
        updates = {
            "email_hash": sent.hash,
            "email_verified": False,
            "email_expires_at": sent.expires_at,
        }
        email_expires_at = sent.expires_at
    elif channel == "phone":
        sent = await send_otp(phone_e164=phone_e164(doc["phone"]))
        updates = {
            "phone_hash": sent.hash,
            "phone_verified": False,
            "phone_expires_at": sent.expires_at,
        }
        phone_expires_at = sent.expires_at
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica si quieres reenviar el código de correo o de teléfono.",
        )

    await collection.update_one({"_id": doc["_id"]}, {"$set": updates})
    doc.update(updates)
    doc["email_expires_at"] = email_expires_at
    doc["phone_expires_at"] = phone_expires_at
    return _start_response(doc, message="Código reenviado.")


async def confirm_password_reset_otp(
    *,
    challenge_id: str,
    email_code: str,
    phone_code: str,
) -> PasswordResetConfirmResponse:
    doc = await _get_challenge(challenge_id)
    await verify_otp(otp_hash=doc.get("email_hash") or "", code=email_code)
    await verify_otp(otp_hash=doc.get("phone_hash") or "", code=phone_code)
    await get_password_reset_challenges_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": {"email_verified": True, "phone_verified": True}},
    )
    return PasswordResetConfirmResponse(
        challenge_id=challenge_id,
        message="Identidad confirmada. Elige una nueva contraseña.",
    )


async def complete_password_reset(
    *,
    challenge_id: str,
    password: str,
) -> PasswordResetCompleteResponse:
    doc = await _get_challenge(challenge_id)
    if not doc.get("email_verified") or not doc.get("phone_verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Primero confirma el correo y el SMS.",
        )

    try:
        seller_oid = ObjectId(doc["seller_id"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ACCOUNT_NOT_FOUND,
        ) from exc

    now = to_utc_naive(utc_now())
    result = await get_registrations_collection().update_one(
        {"_id": seller_oid},
        {"$set": {"password_hash": hash_password(password), "updated_at": now}},
    )
    await get_password_reset_challenges_collection().delete_one({"_id": doc["_id"]})
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ACCOUNT_NOT_FOUND)
    return PasswordResetCompleteResponse(
        message="Contraseña actualizada. Ya puedes iniciar sesión.",
    )
