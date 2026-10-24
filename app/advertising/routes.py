from fastapi import APIRouter, Depends

from app.advertising.schemas import AdvertisingCheckoutPublic, AdvertisingCheckoutRequest
from app.advertising.service import checkout_advertising_plan
from app.auth.utils import require_seller

router = APIRouter(prefix="/api/advertising", tags=["advertising"])


@router.post("/checkout", response_model=AdvertisingCheckoutPublic)
async def checkout_plan(
    payload: AdvertisingCheckoutRequest,
    seller_payload: dict = Depends(require_seller),
):
    return await checkout_advertising_plan(
        seller_id=seller_payload["seller_id"],
        plan_id=payload.plan_id.strip(),
    )
