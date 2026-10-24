from typing import Any

from fastapi import HTTPException, status

from app.notifications.otp_manager import nox_provider
from app.notifications.otp_manager.nox_provider import OtpSendResult
from app.notifications.otp_manager.sms_cooldown import (
    OTP_SMS_FAILED_CODE,
    OTP_SMS_FAILED_MESSAGE,
    ensure_sms_cooldown_indexes,
)
from app.utils.phone import can_send_sms, to_e164

OTP_EXPIRES_IN_SECONDS = nox_provider.OTP_EXPIRES_IN_SECONDS


async def send_otp(*, email: str | None = None, phone_e164: str | None = None) -> OtpSendResult:
    email_value = str(email).strip() if email else None
    phone_value = to_e164(phone_e164) if phone_e164 else ""
    sms_phone = phone_value if phone_value and can_send_sms(phone_value) else None
    if phone_e164 and not sms_phone and not email_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo enviamos SMS a números de Cuba (+53).",
        )
    return await nox_provider.send_otp(email=email_value, phone_e164=sms_phone)


async def verify_otp(*, otp_hash: str, code: str) -> None:
    await nox_provider.verify_otp(otp_hash=otp_hash, code=code)


async def send_custom_sms(*, phone_e164: str, message: str) -> dict[str, Any]:
    phone = to_e164(phone_e164)
    if not can_send_sms(phone):
        return {"success": False, "skipped": True, "reason": "sms_not_cuba"}
    return await nox_provider.send_custom_sms(phone_e164=phone, message=message)


async def send_sms_campaign(*, name: str, message: str, recipients: list[str]) -> dict[str, Any]:
    cuba_phones: list[str] = []
    seen: set[str] = set()
    for raw in recipients:
        phone = to_e164(raw)
        if not phone or phone in seen or not can_send_sms(phone):
            continue
        seen.add(phone)
        cuba_phones.append(phone)
    if not cuba_phones:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay teléfonos de Cuba (+53) para enviar el SMS del aviso.",
        )
    return await nox_provider.send_sms_campaign(name=name, message=message, recipients=cuba_phones)


__all__ = [
    "OTP_EXPIRES_IN_SECONDS",
    "OTP_SMS_FAILED_CODE",
    "OTP_SMS_FAILED_MESSAGE",
    "OtpSendResult",
    "can_send_sms",
    "ensure_sms_cooldown_indexes",
    "send_custom_sms",
    "send_otp",
    "send_sms_campaign",
    "to_e164",
    "verify_otp",
]
