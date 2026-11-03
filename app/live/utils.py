from fastapi import HTTPException, status
from bson import ObjectId

from app.auth.utils import decode_customer_token, decode_seller_token
from app.database import get_customers_collection, get_registrations_collection


async def seller_id_from_access_token(token: str) -> str:
    payload = decode_seller_token(token.strip())
    if payload is None or not payload.get("seller_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )
    seller_id = str(payload["seller_id"])
    try:
        seller_oid = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado") from exc
    seller = await get_registrations_collection().find_one(
        {"_id": seller_oid},
        {"status": 1, "deleted_at": 1},
    )
    if seller is None or seller.get("deleted_at") or seller.get("status") not in {"approved", "expired"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cuenta de tienda no encontrada.")
    return seller_id


async def customer_id_from_access_token(token: str) -> str:
    payload = decode_customer_token(token.strip())
    if payload is None or not payload.get("customer_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    customer_id = str(payload["customer_id"])
    try:
        customer_oid = ObjectId(customer_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado") from exc
    customer = await get_customers_collection().find_one({"_id": customer_oid}, {"_id": 1})
    if customer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cuenta de cliente no encontrada.")
    return customer_id
