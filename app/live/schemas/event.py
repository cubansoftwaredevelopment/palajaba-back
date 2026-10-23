from typing import Literal

from pydantic import BaseModel

from app.notifications.schemas import SellerNotificationPublic


class LiveNotificationEvent(BaseModel):
    type: Literal["notification"] = "notification"
    notification: SellerNotificationPublic
