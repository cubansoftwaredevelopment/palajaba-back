from fastapi import HTTPException, status

from app.security import decode_seller_token
from app.services.subscriptions import assert_seller_subscription_active


async def seller_id_from_access_token(token: str) -> str:
    payload = decode_seller_token(token.strip())
    if payload is None or not payload.get("seller_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )
    seller_id = str(payload["seller_id"])
    await assert_seller_subscription_active(seller_id)
    return seller_id
