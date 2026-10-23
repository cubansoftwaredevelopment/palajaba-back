from pydantic import BaseModel

from app.utils.datetime import UtcDateTime


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
