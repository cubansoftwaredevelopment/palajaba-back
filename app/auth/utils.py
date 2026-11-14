from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

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


def create_customer_token(*, customer_id: str, full_name: str) -> str:
    payload = {
        "sub": full_name,
        "customer_id": customer_id,
        "role": "customer",
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


def decode_customer_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("role") != "customer":
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

    from bson import ObjectId
    from app.database import get_registrations_collection

    try:
        seller_oid = ObjectId(str(payload.get("seller_id") or ""))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    seller = await get_registrations_collection().find_one(
        {"_id": seller_oid},
        {"deleted_at": 1},
    )
    if seller is None or seller.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cuenta de tienda no encontrada.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


INACTIVE_SUBSCRIPTION_DETAIL = "Tu suscripción está inactiva. Renueva el plan para volver a operar."


async def require_active_seller(
    seller_payload: dict = Depends(require_seller),
) -> dict:
    from bson import ObjectId

    from app.auth.registrations import mark_registration_expired_if_needed
    from app.database import get_registrations_collection
    from app.subscriptions.service import is_subscription_active

    try:
        seller_oid = ObjectId(str(seller_payload.get("seller_id") or ""))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    doc = await get_registrations_collection().find_one({"_id": seller_oid})
    if doc is None or not is_subscription_active(doc):
        if doc is not None:
            await mark_registration_expired_if_needed(doc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=INACTIVE_SUBSCRIPTION_DETAIL,
        )
    return seller_payload


async def require_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_customer_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from bson import ObjectId
    from app.database import get_customers_collection

    try:
        customer_id = ObjectId(payload["customer_id"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado") from exc
    customer = await get_customers_collection().find_one({"_id": customer_id}, {"_id": 1})
    if customer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cuenta de cliente no encontrada.")
    return payload


async def require_customer_or_seller(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Auth para endpoints que aceptan cliente o vendedor (p. ej. registro de descarga de app)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    customer_payload = decode_customer_token(token)
    if customer_payload is not None:
        customer = await require_customer(credentials)
        return {
            "user_type": "customer",
            "user_id": str(customer["customer_id"]),
            **customer,
        }
    seller_payload = decode_seller_token(token)
    if seller_payload is not None:
        seller = await require_seller(credentials)
        return {
            "user_type": "seller",
            "user_id": str(seller["seller_id"]),
            **seller,
        }
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )


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

    from app.services.gestores import assert_gestor_account_active

    await assert_gestor_account_active(payload["gestor_id"], payload["seller_id"])

    return payload
