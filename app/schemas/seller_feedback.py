from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.datetime import UtcDateTime

FeedbackType = Literal["complaint", "suggestion"]


class SellerFeedbackCreate(BaseModel):
    feedback_type: FeedbackType
    message: str = Field(..., min_length=10, max_length=2000)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError("Escribe al menos 10 caracteres.")
        return cleaned


class SellerFeedbackSubmitResult(BaseModel):
    id: str
    message: str


class AdminFeedbackPublic(BaseModel):
    id: str
    seller_id: str
    store_name: str
    store_slug: str | None = None
    feedback_type: FeedbackType
    message: str
    read_at: UtcDateTime | None = None
    created_at: UtcDateTime


class AdminFeedbackUnreadCount(BaseModel):
    unread_count: int


class AdminFeedbackDeleteResult(BaseModel):
    id: str
    message: str
