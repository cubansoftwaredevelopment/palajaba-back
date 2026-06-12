from typing import Any

from fastapi import HTTPException, status

from app.database import get_registrations_collection
from app.schemas.auth import SubscriptionExpiredPublic
from app.security import verify_password
from app.services.platform_settings import get_renewal_contact_phone
from app.services.registrations import mark_registration_expired_if_needed
from app.services.subscriptions import is_subscription_active, subscription_expired_detail



async def _subscription_expired_public(doc: dict[str, Any]) -> SubscriptionExpiredPublic:
    detail = subscription_expired_detail(doc)
    detail["renewal_contact_phone"] = await get_renewal_contact_phone()
    return SubscriptionExpiredPublic(**detail)


async def login_seller(
    *,
    method: str,
    password: str,
    phone: str | None = None,
    store_name: str | None = None,
) -> dict[str, Any] | SubscriptionExpiredPublic:
    collection = get_registrations_collection()

    if method == "phone":
        doc = await collection.find_one({"phone": phone})
    else:
        doc = await collection.find_one(
            {"store_name": {"$regex": f"^{store_name}$", "$options": "i"}}
        )

    if doc is None or not verify_password(password, doc["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    if doc["status"] == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Tu solicitud está en revisión. Te notificaremos cuando "
                "verifiquemos tu pago."
            ),
        )

    if doc["status"] == "rejected":
        reason = doc.get("rejection_reason") or "No pudimos confirmar tu pago."
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Solicitud rechazada: {reason}",
        )

    if doc["status"] == "expired":
        return await _subscription_expired_public(doc)

    if doc["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta no está activa.",
        )

    if not is_subscription_active(doc):
        await mark_registration_expired_if_needed(doc)
        return await _subscription_expired_public(doc)

    return doc


async def authenticate_seller(
    *,
    method: str,
    password: str,
    phone: str | None = None,
    store_name: str | None = None,
) -> dict[str, Any]:
    result = await login_seller(
        method=method,
        password=password,
        phone=phone,
        store_name=store_name,
    )
    if isinstance(result, SubscriptionExpiredPublic):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=result.model_dump(),
        )
    return result
