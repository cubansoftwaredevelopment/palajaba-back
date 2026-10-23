from datetime import timedelta

from bson import ObjectId
from fastapi import HTTPException, status

from app.database import get_registration_otp_challenges_collection
from app.register.otp import OTP_EXPIRES_IN_SECONDS, send_otp, verify_otp
from app.register.schemas.otp import (
    RegisterOtpConfirmResponse,
    RegisterOtpStartResponse,
    RegisterRequest,
)
from app.security import create_seller_token, hash_password
from app.services.registrations import (
    assert_contact_available,
    create_registration,
    phone_e164,
)
from app.utils.datetime import to_utc_naive, utc_now

CHALLENGE_TTL_SECONDS = OTP_EXPIRES_IN_SECONDS


def _challenge_object_id(challenge_id: str) -> ObjectId:
    try:
        return ObjectId(challenge_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a enviar tus datos.",
        ) from exc


async def ensure_registration_otp_indexes() -> None:
    collection = get_registration_otp_challenges_collection()
    await collection.create_index("expires_at", expireAfterSeconds=0)
    await collection.create_index("email")
    await collection.create_index("phone")
    from app.register.sms_cooldown import ensure_sms_cooldown_indexes

    await ensure_sms_cooldown_indexes()


async def _get_challenge(challenge_id: str) -> dict:
    collection = get_registration_otp_challenges_collection()
    doc = await collection.find_one({"_id": _challenge_object_id(challenge_id)})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a enviar tus datos.",
        )
    expires_at = doc.get("expires_at")
    if expires_at and to_utc_naive(expires_at) <= to_utc_naive(utc_now()):
        await collection.delete_one({"_id": doc["_id"]})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La verificación expiró. Vuelve a enviar tus datos.",
        )
    return doc


async def start_registration_otp(payload: RegisterRequest) -> RegisterOtpStartResponse:
    await assert_contact_available(
        phone=payload.phone,
        email=payload.email,
        store_name=payload.store_name,
    )
    now = to_utc_naive(utc_now())
    collection = get_registration_otp_challenges_collection()
    phone_result = await send_otp(phone_e164=phone_e164(payload.phone))
    email_result = await send_otp(email=payload.email)
    document = {
        "kind": payload.kind,
        "transfer_id": payload.transfer_id,
        "store_name": payload.store_name,
        "email": payload.email,
        "phone": payload.phone,
        "password_hash": hash_password(payload.password),
        "billing_period": payload.billing_period,
        "plan_tier": payload.plan_tier,
        "discount_code": payload.discount_code,
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
    return RegisterOtpStartResponse(
        challenge_id=str(result.inserted_id),
        email_expires_at=email_result.expires_at,
        phone_expires_at=phone_result.expires_at,
        message="Te enviamos un código al correo y otro por SMS.",
    )


async def resend_registration_otp(*, challenge_id: str, channel: str) -> RegisterOtpStartResponse:
    doc = await _get_challenge(challenge_id)
    collection = get_registration_otp_challenges_collection()
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
    return RegisterOtpStartResponse(
        challenge_id=challenge_id,
        email_expires_at=email_expires_at,
        phone_expires_at=phone_expires_at,
        message="Código reenviado.",
    )


async def confirm_registration_otp(
    *,
    challenge_id: str,
    email_code: str,
    phone_code: str,
) -> RegisterOtpConfirmResponse:
    doc = await _get_challenge(challenge_id)
    collection = get_registration_otp_challenges_collection()

    if not doc.get("email_verified"):
        await verify_otp(otp_hash=doc.get("email_hash") or "", code=email_code)
        await collection.update_one({"_id": doc["_id"]}, {"$set": {"email_verified": True}})
    if not doc.get("phone_verified"):
        await verify_otp(otp_hash=doc.get("phone_hash") or "", code=phone_code)
        await collection.update_one({"_id": doc["_id"]}, {"$set": {"phone_verified": True}})

    is_trial = doc.get("kind") == "trial"
    registration = await create_registration(
        transfer_id=doc.get("transfer_id"),
        store_name=doc["store_name"],
        phone=doc["phone"],
        email=doc["email"],
        password_hash=doc["password_hash"],
        billing_period=doc.get("billing_period") or "monthly",
        plan_tier=doc.get("plan_tier") or "standard",
        discount_code=doc.get("discount_code"),
        is_trial=is_trial,
    )
    await collection.delete_one({"_id": doc["_id"]})

    access_token = None
    if is_trial:
        access_token = create_seller_token(
            seller_id=registration.id,
            store_name=registration.store_name,
        )
        message = "Tu prueba de 15 días ya está activa. Puedes entrar a tu tienda."
    else:
        message = "Solicitud recibida. Te notificaremos cuando verifiquemos tu pago."

    return RegisterOtpConfirmResponse(
        id=registration.id,
        status=registration.status,
        kind="trial" if is_trial else "paid",
        message=message,
        access_token=access_token,
    )
