from fastapi import APIRouter, Depends, status

from app.dependencies import require_seller
from app.live.devices import delete_seller_device, register_seller_device
from app.live.schemas.device import SellerDeviceDelete, SellerDevicePublic, SellerDeviceRegister

router = APIRouter()


@router.post("/devices", response_model=SellerDevicePublic)
async def register_device(
    payload: SellerDeviceRegister,
    seller: dict = Depends(require_seller),
) -> SellerDevicePublic:
    return await register_seller_device(seller["seller_id"], payload)


@router.delete("/devices", status_code=status.HTTP_204_NO_CONTENT)
async def remove_device(
    payload: SellerDeviceDelete,
    seller: dict = Depends(require_seller),
) -> None:
    await delete_seller_device(seller["seller_id"], payload.token)
