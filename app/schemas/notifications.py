from pydantic import BaseModel, Field

from app.utils.datetime import UtcDateTime


class AdminNotificationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)


class AdminNotificationSendResult(BaseModel):
    batch_id: str
    title: str
    content: str
    recipient_count: int
    created_at: UtcDateTime


class AdminNotificationBroadcastPublic(BaseModel):
    batch_id: str
    title: str
    content: str
    recipient_count: int
    created_at: UtcDateTime


class SellerNotificationPublic(BaseModel):
    id: str
    title: str
    content: str
    read_at: UtcDateTime | None
    created_at: UtcDateTime
    kind: str | None = None
    action_label: str | None = None
    action_type: str | None = None


class SellerNotificationUnreadCount(BaseModel):
    count: int
