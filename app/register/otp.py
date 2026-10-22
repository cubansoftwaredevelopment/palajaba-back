from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import settings

# OTP Cuba solo acepta 60–600 segundos.
OTP_EXPIRES_IN_SECONDS = 600


class OtpSendResult:
    def __init__(self, hash: str, expires_at: str | None = None, message: str | None = None):
        self.hash = hash
        self.expires_at = expires_at
        self.message = message


def _otp_configured() -> bool:
    return bool(settings.otp_api_key.strip() and settings.otp_token_secret.strip())


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": settings.otp_api_key.strip(),
        "x-token-secret": settings.otp_token_secret.strip(),
    }


def _otp_url(path: str) -> str:
    return f"{settings.otp_api_base.rstrip('/')}/{path.lstrip('/')}"


def _parse_json(response: httpx.Response) -> Any:
    if not response.content or not response.content.strip():
        return {}
    try:
        return response.json()
    except ValueError:
        return None


def _detail_from_payload(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _raise_otp_http_error(response: httpx.Response, *, fallback: str) -> None:
    payload = _parse_json(response)
    message = _detail_from_payload(payload, fallback)

    if response.status_code == 402:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el SMS de verificación. Inténtalo de nuevo en unos minutos.",
        )
    if response.status_code == 429:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message
            or "Ya hay un código pendiente. Espera 10 minutos para pedir otro.",
        )
    if response.status_code in (400, 404):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de verificación no está disponible.",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No pudimos contactar el servicio de verificación.",
    )


async def send_otp(*, email: str | None = None, phone_e164: str | None = None) -> OtpSendResult:
    if not _otp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de verificación no está configurado.",
        )
    if not email and not phone_e164:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica un correo o un teléfono para enviar el código.",
        )

    body: dict[str, Any] = {"expiresInSeconds": OTP_EXPIRES_IN_SECONDS}
    if email:
        body["email"] = email
    if phone_e164:
        body["phoneNumber"] = phone_e164

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(_otp_url("send"), headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el código de verificación.",
        ) from exc

    if response.status_code >= 400:
        _raise_otp_http_error(
            response,
            fallback="No pudimos enviar el código de verificación.",
        )

    payload = _parse_json(response)
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el código de verificación.",
        )
    otp_hash = str(payload.get("hash") or "").strip()
    if not otp_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el código de verificación.",
        )
    expires_at = payload.get("expiresAt")
    return OtpSendResult(
        hash=otp_hash,
        expires_at=str(expires_at) if expires_at else None,
        message=payload.get("message"),
    )


def _campaign_url() -> str:
    base = settings.otp_api_base.rstrip("/")
    if base.endswith("/api/v2"):
        return f"{base}/sms/campaign"
    if base.endswith("/api"):
        return f"{base}/v2/sms/campaign"
    return f"{base}/v2/sms/campaign"


def _campaign_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-token-secret": settings.otp_token_secret.strip(),
    }


def _raise_campaign_http_error(response: httpx.Response) -> None:
    payload = _parse_json(response)
    message = _detail_from_payload(payload, "No pudimos enviar el SMS del aviso.")

    if response.status_code == 402:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=message or "No hay saldo suficiente para enviar los SMS del aviso.",
        )
    if response.status_code == 429:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message or "Demasiados envíos de SMS. Espera unos segundos e inténtalo de nuevo.",
        )
    if response.status_code in (400, 404):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de SMS no está disponible.",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=message or "No pudimos enviar el SMS del aviso.",
    )


async def send_sms_campaign(*, name: str, message: str, recipients: list[str]) -> dict[str, Any]:
    if not settings.otp_token_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de SMS no está configurado.",
        )
    phones: list[str] = []
    seen: set[str] = set()
    for raw in recipients:
        phone = str(raw or "").strip()
        if not phone or phone in seen:
            continue
        seen.add(phone)
        phones.append(phone)
    if not phones:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay teléfonos para enviar el SMS del aviso.",
        )

    body = {
        "name": name.strip()[:120],
        "message": message.strip(),
        "recipients": phones,
    }
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                _campaign_url(),
                headers=_campaign_headers(),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el SMS del aviso.",
        ) from exc

    if response.status_code >= 400:
        _raise_campaign_http_error(response)

    payload = _parse_json(response)
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el SMS del aviso.",
        )
    if payload.get("success") is False:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_detail_from_payload(payload, "No pudimos enviar el SMS del aviso."),
        )
    return payload


async def verify_otp(*, otp_hash: str, code: str) -> None:
    if not _otp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de verificación no está configurado.",
        )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                _otp_url("verify"),
                headers=_headers(),
                json={"hash": otp_hash, "code": code.strip()},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos verificar el código.",
        ) from exc

    if response.status_code >= 400:
        _raise_otp_http_error(response, fallback="El código no es válido.")
