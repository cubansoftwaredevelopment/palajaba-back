import json
import time
from pathlib import Path

import httpx
from jose import jwt

from app.config import settings
from app.live.devices import (
    list_customer_device_tokens,
    list_device_tokens_for_platform,
    list_seller_device_tokens,
)

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_cached_access_token = ""
_cached_access_token_exp = 0


def _account() -> dict | None:
    path = settings.firebase_service_account_file.strip()
    if not path:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


async def _access_token(account: dict) -> str | None:
    global _cached_access_token, _cached_access_token_exp
    now = int(time.time())
    if _cached_access_token and now < _cached_access_token_exp - 60:
        return _cached_access_token

    assertion = jwt.encode(
        {
            "iss": account["client_email"],
            "scope": _FCM_SCOPE,
            "aud": _TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        account["private_key"],
        algorithm="RS256",
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    if response.status_code != 200:
        return None
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        return None
    _cached_access_token = token
    _cached_access_token_exp = now + int(payload.get("expires_in") or 3600)
    return token


# Canal Android (debe coincidir con PushNotifications.createChannel en el front).
ANDROID_PUSH_CHANNEL_ID = "pala_jaba_push"


def _fcm_message(token: str, title: str, body: str, data: dict | None = None) -> dict:
    """Payload con notification + android/apns para bandeja del sistema en background."""
    clean_title = str(title or "").strip() or "Pa' La Jaba"
    clean_body = str(body or "").replace("\n", " ").strip() or "Tienes una novedad."
    message: dict = {
        "token": token,
        "notification": {
            "title": clean_title,
            "body": clean_body,
        },
        "android": {
            "priority": "HIGH",
            "notification": {
                "channel_id": ANDROID_PUSH_CHANNEL_ID,
                "title": clean_title,
                "body": clean_body,
                "sound": "default",
                "default_sound": True,
                "default_vibrate_timings": True,
                "notification_priority": "PRIORITY_HIGH",
            },
        },
        "apns": {
            "headers": {
                "apns-priority": "10",
            },
            "payload": {
                "aps": {
                    "alert": {
                        "title": clean_title,
                        "body": clean_body,
                    },
                    "sound": "default",
                }
            },
        },
    }
    if data:
        message["data"] = {str(key): str(value) for key, value in data.items()}
    return message


async def notify_device_tokens(tokens: list[str], title: str, body: str, data: dict | None = None) -> None:
    account = _account()
    if account is None or not account.get("project_id"):
        return
    if not tokens:
        return

    try:
        access_token = await _access_token(account)
    except Exception:
        return
    if not access_token:
        return

    url = f"https://fcm.googleapis.com/v1/projects/{account['project_id']}/messages:send"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for device_token in tokens:
                await client.post(
                    url,
                    headers=headers,
                    json={"message": _fcm_message(device_token, title, body, data)},
                )
    except Exception:
        return


async def notify_seller_devices(
    seller_id: str,
    title: str,
    body: str,
    *,
    notification_id: str | None = None,
    kind: str | None = None,
) -> None:
    data = {
        "screen": "seller_notifications",
        "notification_id": str(notification_id or ""),
        "kind": str(kind or ""),
    }
    await notify_device_tokens(
        await list_seller_device_tokens(seller_id), title, body, data=data
    )


async def notify_customer_devices(
    customer_id: str,
    title: str,
    body: str,
    *,
    order_id: str | None = None,
    notification_id: str | None = None,
) -> None:
    data = {
        "screen": "customer_avisos",
        "notification_id": str(notification_id or ""),
    }
    if order_id:
        data["order_id"] = str(order_id)
    await notify_device_tokens(
        await list_customer_device_tokens(customer_id), title, body, data=data
    )


async def notify_app_update_devices(*, platform: str, version: str) -> None:
    """Avisa a todos los dispositivos de la plataforma que hay un build main nuevo."""
    normalized_platform = str(platform or "").strip().lower()
    normalized_version = str(version or "").strip()
    if normalized_platform not in ("android", "ios") or not normalized_version:
        return
    label = "Android" if normalized_platform == "android" else "Apple"
    title = f"Actualización {label}"
    body = f"Ya está disponible la versión {normalized_version}. Ábrela para actualizar Pa' La Jaba."
    data = {
        "screen": "app_update",
        "platform": normalized_platform,
        "version": normalized_version,
    }
    await notify_device_tokens(
        await list_device_tokens_for_platform(normalized_platform),
        title,
        body,
        data=data,
    )
