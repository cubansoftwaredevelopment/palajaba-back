from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.utils.datetime import UtcDateTime

NotificationAudienceInput = Literal[
    "all",
    "premium_monthly",
    "premium_yearly",
    "standard_monthly",
    "standard_yearly",
    "single",
]

NotificationAudience = NotificationAudienceInput | Literal["premium", "standard", "mixed"]
NotificationGroupAudience = Literal[
    "all",
    "premium_monthly",
    "premium_yearly",
    "standard_monthly",
    "standard_yearly",
]


class AdminNotificationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    audience: NotificationAudienceInput = "all"
    audiences: list[NotificationGroupAudience] = Field(default_factory=list)
    seller_id: str | None = Field(default=None, min_length=1, max_length=40)
    seller_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self) -> "AdminNotificationCreate":
        ids: list[str] = []
        seen: set[str] = set()
        for raw in [self.seller_id, *self.seller_ids]:
            value = (raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ids.append(value)
        self.seller_ids = ids
        self.seller_id = ids[0] if len(ids) == 1 else None

        groups: list[NotificationGroupAudience] = []
        seen_groups: set[str] = set()
        for raw in self.audiences:
            if raw in seen_groups:
                continue
            seen_groups.add(raw)
            groups.append(raw)

        if not groups and self.audience not in ("single",):
            groups = [self.audience]  # type: ignore[list-item]
            if groups[0] == "single":
                groups = []

        if "all" in groups:
            groups = ["all"]

        self.audiences = groups

        if not groups and not ids:
            if self.audience == "single":
                raise ValueError("Indica el negocio destinatario (seller_id).")
            self.audiences = ["all"]
        return self


class AdminNotificationSendResult(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    audiences: list[str] = Field(default_factory=list)
    recipient_count: int
    created_at: UtcDateTime
    target_store_name: str | None = None


class AdminNotificationBroadcastPublic(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    audiences: list[str] = Field(default_factory=list)
    recipient_count: int
    created_at: UtcDateTime
    target_store_name: str | None = None


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
