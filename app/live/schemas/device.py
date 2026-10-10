from typing import Literal

from pydantic import BaseModel, Field

from app.utils.datetime import UtcDateTime

DevicePlatform = Literal["android", "ios"]


class SellerDeviceRegister(BaseModel):
    token: str = Field(..., min_length=8, max_length=4096)
    platform: DevicePlatform


class SellerDeviceDelete(BaseModel):
    token: str = Field(..., min_length=8, max_length=4096)


class SellerDevicePublic(BaseModel):
    token: str
    platform: DevicePlatform
    updated_at: UtcDateTime
