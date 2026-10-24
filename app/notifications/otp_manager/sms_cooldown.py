from datetime import timedelta

from fastapi import HTTPException, status

from app.database import get_registration_otp_sms_cooldowns_collection
from app.utils.datetime import serialize_utc_datetime, to_utc_naive, utc_now

SMS_FAIL_RETRY_SECONDS = 2 * 60
OTP_SMS_FAILED_CODE = "otp_sms_failed"
OTP_SMS_FAILED_MESSAGE = (
    "No pudimos enviar el código. Revisa el número de teléfono y espera 2 minutos "
    "para intentarlo de nuevo."
)


def phone_cooldown_key(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("53") and len(digits) == 10:
        digits = digits[2:]
    return digits[-8:] if len(digits) >= 8 else digits


def sms_fail_http_exception(retry_available_at) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": OTP_SMS_FAILED_CODE,
            "message": OTP_SMS_FAILED_MESSAGE,
            "retry_available_at": serialize_utc_datetime(retry_available_at),
        },
    )


async def ensure_sms_cooldown_indexes() -> None:
    collection = get_registration_otp_sms_cooldowns_collection()
    await collection.create_index("phone", unique=True)
    await collection.create_index("expires_at", expireAfterSeconds=0)


async def get_sms_cooldown_until(phone: str):
    key = phone_cooldown_key(phone)
    if not key:
        return None
    doc = await get_registration_otp_sms_cooldowns_collection().find_one({"phone": key})
    if not doc:
        return None
    until = to_utc_naive(doc["blocked_until"])
    if until <= to_utc_naive(utc_now()):
        await get_registration_otp_sms_cooldowns_collection().delete_one({"phone": key})
        return None
    return until


async def raise_if_sms_cooldown(phone: str) -> None:
    until = await get_sms_cooldown_until(phone)
    if until:
        raise sms_fail_http_exception(until)


async def mark_sms_cooldown(phone: str):
    now = to_utc_naive(utc_now())
    until = now + timedelta(seconds=SMS_FAIL_RETRY_SECONDS)
    key = phone_cooldown_key(phone)
    await get_registration_otp_sms_cooldowns_collection().update_one(
        {"phone": key},
        {
            "$set": {
                "phone": key,
                "blocked_until": until,
                "expires_at": until,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return until
