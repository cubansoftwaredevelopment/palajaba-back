from fastapi import APIRouter, Depends

from app.auth.utils import require_admin
from app.notifications import service
from app.notifications.schemas import (
    AdminNotificationBroadcastPublic,
    AdminNotificationCreate,
    AdminNotificationSendResult,
)

router = APIRouter(prefix="/api/admin", tags=["notifications"])


@router.get("/notifications", response_model=list[AdminNotificationBroadcastPublic])
async def list_notifications(_: dict = Depends(require_admin)):
    return await service.list_admin_broadcasts()


@router.post("/notifications", response_model=AdminNotificationSendResult)
async def send_notification(
    payload: AdminNotificationCreate,
    admin_payload: dict = Depends(require_admin),
):
    return await service.send_notification_to_sellers(
        admin_payload["admin_id"],
        payload.title,
        payload.content,
        payload.audience,
        seller_id=payload.seller_id,
        audiences=payload.audiences,
        seller_ids=payload.seller_ids,
    )
