from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.utils.datetime import UtcDateTime

NotificationAudienceInput = Literal[
    "all",
    "premium_monthly",
    "premium_quarterly",
    "premium_yearly",
    "pro_monthly",
    "pro_quarterly",
    "pro_yearly",
    "standard_monthly",
    "standard_quarterly",
    "standard_yearly",
    "single",
]

NotificationAudience = NotificationAudienceInput | Literal["premium", "pro", "standard"]


class AdminNotificationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    audience: NotificationAudienceInput = "all"
    seller_id: str | None = Field(default=None, min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_single_target(self) -> "AdminNotificationCreate":
        seller_id = (self.seller_id or "").strip() or None
        self.seller_id = seller_id

        if seller_id is not None:
            self.audience = "single"
            return self

        if self.audience == "single":
            raise ValueError("Indica el negocio destinatario (seller_id).")
        return self


class AdminNotificationSendEvent(BaseModel):
    type: Literal["success", "error"]
    message: str


class AdminNotificationSendResult(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    recipient_count: int
    created_at: UtcDateTime
    target_store_name: str | None = None
    sms_sent: bool = True
    sms_error: str | None = None
    events: list[AdminNotificationSendEvent] = Field(default_factory=list)


class AdminNotificationBroadcastPublic(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    recipient_count: int
    created_at: UtcDateTime
    target_store_name: str | None = None
