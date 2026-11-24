from fastapi import APIRouter, Depends

from app.admin.schemas import AdvertisingPlansPublic
from app.advertising.schemas import AdvertisingCheckoutPublic, AdvertisingCheckoutRequest
from app.advertising.service import checkout_advertising_plan, list_public_advertising_plans
from app.auth.utils import require_active_seller

router = APIRouter(prefix="/api/advertising", tags=["advertising"])
platform_router = APIRouter(prefix="/api/platform", tags=["platform"])


@platform_router.get("/advertising-plans", response_model=AdvertisingPlansPublic)
async def get_advertising_plans():
    plans = await list_public_advertising_plans()
    return AdvertisingPlansPublic(plans=plans)


@router.post("/checkout", response_model=AdvertisingCheckoutPublic)
async def checkout_plan(
    payload: AdvertisingCheckoutRequest,
    seller_payload: dict = Depends(require_active_seller),
):
    return await checkout_advertising_plan(
        seller_id=seller_payload["seller_id"],
        plan_id=payload.plan_id.strip(),
    )
