from fastapi import HTTPException, status
from bson import ObjectId

from app.auth.utils import decode_seller_token
from app.database import get_registrations_collection


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
    seller = await get_registrations_collection().find_one({"_id": seller_oid}, {"status": 1})
    if seller is None or seller.get("status") not in {"approved", "expired"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cuenta de tienda no encontrada.")
    return seller_id
