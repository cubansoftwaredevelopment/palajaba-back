from datetime import datetime

from pydantic import BaseModel, Field


class AdminNotificationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)


class AdminNotificationSendResult(BaseModel):
    batch_id: str
    title: str
    content: str
    recipient_count: int
    created_at: datetime


class AdminNotificationBroadcastPublic(BaseModel):
    batch_id: str
    title: str
    content: str
    recipient_count: int
    created_at: datetime


class SellerNotificationPublic(BaseModel):
    id: str
    title: str
    content: str
    read_at: datetime | None
    created_at: datetime
    kind: str | None = None
    action_label: str | None = None
    action_type: str | None = None


class SellerNotificationUnreadCount(BaseModel):
    count: int
