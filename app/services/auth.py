from typing import Any

from fastapi import HTTPException, status

from app.database import get_registrations_collection
from app.security import verify_password
from app.services.subscriptions import is_subscription_active, raise_subscription_expired


async def authenticate_seller(
    *,
    method: str,
    password: str,
    phone: str | None = None,
    store_name: str | None = None,
) -> dict[str, Any]:
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

    if doc["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta no está activa.",
        )

    if not is_subscription_active(doc):
        raise_subscription_expired(doc)

    return doc
