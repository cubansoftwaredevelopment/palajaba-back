from datetime import date

from fastapi import APIRouter, Depends

from app.auth.utils import require_seller
from app.notifications import service
from app.notifications.schemas import (
    SellerNotificationBulkReadResult,
    SellerNotificationPublic,
    SellerNotificationUnreadCount,
)

router = APIRouter(prefix="/api/auth", tags=["notifications"])


@router.get("/me/notifications", response_model=list[SellerNotificationPublic])
async def list_my_notifications(
    date_from: date | None = None,
    date_to: date | None = None,
    seller_payload: dict = Depends(require_seller),
):
    return await service.list_seller_notifications(
        seller_payload["seller_id"],
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/me/notifications/unread-count", response_model=SellerNotificationUnreadCount)
async def my_notifications_unread_count(seller_payload: dict = Depends(require_seller)):
    return await service.get_unread_count(seller_payload["seller_id"])


@router.patch("/me/notifications/read-system", response_model=SellerNotificationBulkReadResult)
async def mark_my_system_notifications_read(seller_payload: dict = Depends(require_seller)):
    return await service.mark_system_notifications_read(
        seller_payload["seller_id"],
    )


@router.patch("/me/notifications/{notification_id}/read", response_model=SellerNotificationPublic)
async def mark_my_notification_read(
    notification_id: str,
    seller_payload: dict = Depends(require_seller),
):
    return await service.mark_notification_read(
        seller_payload["seller_id"],
        notification_id,
    )
