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
    "customers",
    "single",
]

NotificationAudience = NotificationAudienceInput | Literal["premium", "pro", "standard", "mixed"]


class AdminNotificationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    audience: NotificationAudienceInput = "all"
    audiences: list[NotificationAudienceInput] = Field(default_factory=list)
    seller_id: str | None = Field(default=None, min_length=1, max_length=40)
    seller_ids: list[str] = Field(default_factory=list)
    customer_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self) -> "AdminNotificationCreate":
        groups = [item for item in self.audiences if item and item != "single"]
        if not groups and self.audience and self.audience != "single":
            groups = [self.audience]
        include_customers = "customers" in groups
        groups = [item for item in groups if item != "customers"]
        if "all" in groups:
            groups = ["all"]
        if include_customers:
            groups.append("customers")

        ids: list[str] = []
        seen: set[str] = set()
        for raw in [*(self.seller_ids or []), self.seller_id or ""]:
            seller_id = str(raw or "").strip()
            if not seller_id or seller_id in seen:
                continue
            seen.add(seller_id)
            ids.append(seller_id)

        customer_ids: list[str] = []
        seen_customers: set[str] = set()
        for raw in self.customer_ids or []:
            customer_id = str(raw or "").strip()
            if not customer_id or customer_id in seen_customers:
                continue
            seen_customers.add(customer_id)
            customer_ids.append(customer_id)

        if not groups and not ids and not customer_ids:
            raise ValueError("Elige al menos un grupo, un negocio o un cliente.")

        self.audiences = groups
        self.seller_ids = ids
        self.customer_ids = customer_ids
        self.seller_id = ids[0] if len(ids) == 1 and not groups else None
        if not groups:
            self.audience = "single"
        elif len(groups) == 1:
            self.audience = groups[0]
        else:
            self.audience = groups[0]
        return self


class AdminNotificationSendEvent(BaseModel):
    type: Literal["success", "error"]
    message: str


class AdminNotificationSendResult(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    audiences: list[str] = Field(default_factory=list)
    recipient_count: int
    created_at: UtcDateTime
    target_store_name: str | None = None
    target_store_names: list[str] = Field(default_factory=list)
    sms_sent: bool = False
    sms_send_count: int = 0
    sms_error: str | None = None
    events: list[AdminNotificationSendEvent] = Field(default_factory=list)


class AdminNotificationBroadcastPublic(BaseModel):
    batch_id: str
    title: str
    content: str
    audience: NotificationAudience
    audiences: list[str] = Field(default_factory=list)
    recipient_count: int
    created_at: UtcDateTime
    target_store_name: str | None = None
    target_store_names: list[str] = Field(default_factory=list)
    sms_send_count: int = 0
