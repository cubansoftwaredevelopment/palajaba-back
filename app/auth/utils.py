from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.database import get_registration_otp_sms_cooldowns_collection
from app.utils.datetime import serialize_utc_datetime, to_utc_naive, utc_now

SMS_FAIL_RETRY_SECONDS = 2 * 60
OTP_SMS_FAILED_CODE = "otp_sms_failed"
OTP_SMS_FAILED_MESSAGE = (
    "No pudimos enviar el código. Revisa el número de teléfono y espera 2 minutos "
    "para intentarlo de nuevo."
)

ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def _token_expiration_timestamp() -> int:
    expire_at = datetime.now(UTC) + timedelta(
        minutes=settings.effective_access_token_expire_minutes
    )
    return int(expire_at.timestamp())


def create_admin_token(*, username: str, admin_id: str) -> str:
    payload = {
        "sub": username,
        "admin_id": admin_id,
        "role": "admin",
        "exp": _token_expiration_timestamp(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_admin_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None

    if payload.get("role") != "admin":
        return None

    return payload


def create_seller_token(*, seller_id: str, store_name: str) -> str:
    payload = {
        "sub": store_name,
        "seller_id": seller_id,
        "role": "seller",
        "exp": _token_expiration_timestamp(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_seller_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None

    if payload.get("role") != "seller":
        return None

    return payload


def create_gestor_token(*, gestor_id: str, seller_id: str, username: str) -> str:
    payload = {
        "sub": username,
        "gestor_id": gestor_id,
        "seller_id": seller_id,
        "username": username,
        "role": "gestor",
        "exp": _token_expiration_timestamp(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_gestor_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None

    if payload.get("role") != "gestor":
        return None

    return payload


def create_gestor_setup_token(
    *,
    gestor_id: str,
    seller_id: str,
    username: str,
    store_name: str,
    expire_minutes: int = 30,
) -> str:
    expire_at = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": username,
        "gestor_id": gestor_id,
        "seller_id": seller_id,
        "username": username,
        "store_name": store_name,
        "role": "gestor_setup",
        "exp": int(expire_at.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_gestor_setup_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None

    if payload.get("role") != "gestor_setup":
        return None

    return payload


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_admin_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def require_seller(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_seller_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.subscriptions.service import assert_seller_subscription_active

    await assert_seller_subscription_active(payload["seller_id"])

    return payload


async def require_gestor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_gestor_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.subscriptions.service import assert_seller_subscription_active
    from app.services.gestores import assert_gestor_account_active

    await assert_seller_subscription_active(payload["seller_id"])
    await assert_gestor_account_active(payload["gestor_id"], payload["seller_id"])

    return payload


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


import asyncio
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


def _sms_provider_failed(response: httpx.Response, payload: Any) -> bool:
    if isinstance(payload, dict) and payload.get("success") is False:
        return True
    if response.status_code in (401, 403, 429):
        return False
    if response.status_code == 402:
        return False
    if response.status_code >= 400:
        return True
    if not isinstance(payload, dict):
        return True
    return not str(payload.get("hash") or "").strip()


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

    if phone_e164:
        await raise_if_sms_cooldown(phone_e164)

    body: dict[str, Any] = {"expiresInSeconds": OTP_EXPIRES_IN_SECONDS}
    if email:
        body["email"] = email
    if phone_e164:
        body["phoneNumber"] = phone_e164

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(_otp_url("send"), headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        if phone_e164:
            until = await mark_sms_cooldown(phone_e164)
            raise sms_fail_http_exception(until) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el código de verificación.",
        ) from exc

    payload = _parse_json(response)
    if phone_e164 and _sms_provider_failed(response, payload):
        until = await mark_sms_cooldown(phone_e164)
        raise sms_fail_http_exception(until)

    if response.status_code >= 400:
        _raise_otp_http_error(
            response,
            fallback="No pudimos enviar el código de verificación.",
        )

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


def _v2_resource_url(resource: str, path: str) -> str:
    base = settings.otp_api_base.rstrip("/")
    suffix = path.lstrip("/")
    name = resource.strip("/")
    if base.endswith("/api/v2"):
        return f"{base}/{name}/{suffix}"
    if base.endswith("/api"):
        return f"{base}/v2/{name}/{suffix}"
    return f"{base}/v2/{name}/{suffix}"


def _v2_sms_url(path: str) -> str:
    return _v2_resource_url("sms", path)


def _campaign_url() -> str:
    return _v2_sms_url("campaign")


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


async def send_custom_sms(*, phone_e164: str, message: str) -> dict[str, Any]:
    if not settings.otp_token_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de SMS no está configurado.",
        )
    phone = str(phone_e164 or "").strip()
    text = str(message or "").strip()
    if not phone or not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica un teléfono y un mensaje para el SMS.",
        )

    body = {"phoneNumber": phone, "message": text}
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    _v2_sms_url("send"),
                    headers=_campaign_headers(),
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No pudimos enviar el SMS del aviso.",
            ) from exc

        if response.status_code == 429 and attempt == 0:
            await asyncio.sleep(3)
            continue
        if response.status_code >= 400:
            _raise_campaign_http_error(response)

        payload = _parse_json(response)
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_detail_from_payload(payload, "No pudimos enviar el SMS del aviso."),
            )
        return payload

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Demasiados envíos de SMS. Espera unos segundos e inténtalo de nuevo.",
    )


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
