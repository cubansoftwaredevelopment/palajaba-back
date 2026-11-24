from datetime import date

from fastapi import APIRouter, Depends, Query

from app.auth.utils import require_seller
from app.notifications import service
from app.notifications.schemas import (
    SellerNotificationBulkReadResult,
    SellerNotificationPublic,
    SellerNotificationUnreadCount,
)

router = APIRouter(prefix="/api/auth", tags=["notifications"])


@router.get("/me/notifications")
async def list_my_notifications(
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1, le=50),
    seller_payload: dict = Depends(require_seller),
):
    if offset is None and limit is None:
        return await service.list_seller_notifications(
            seller_payload["seller_id"],
            date_from=date_from,
            date_to=date_to,
        )
    return await service.list_seller_notifications_page(
        seller_payload["seller_id"],
        offset=offset or 0,
        limit=limit or 10,
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
