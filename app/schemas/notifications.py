from typing import Literal

from pydantic import BaseModel, Field

from app.utils.datetime import UtcDateTime

NotificationAudienceInput = Literal[
    "all",
    "premium_monthly",
    "premium_yearly",
    "standard_monthly",
    "standard_yearly",
]

NotificationAudience = NotificationAudienceInput | Literal["premium", "standard"]


class AdminNotificationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    audience: NotificationAudienceInput = "all"


class AdminNotificationSendResult(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    recipient_count: int
    created_at: UtcDateTime


class AdminNotificationBroadcastPublic(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
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
    from_admin: bool = False


class SellerNotificationUnreadCount(BaseModel):
    count: int


class SellerNotificationBulkReadResult(BaseModel):
    marked_count: int
