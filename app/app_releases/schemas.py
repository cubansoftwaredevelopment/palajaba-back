from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.utils.datetime import UtcDateTime

AppPlatform = Literal["android", "ios"]


class AppReleasePublic(BaseModel):
    id: str
    platform: AppPlatform
    version: str
    original_filename: str
    size_bytes: int
    is_main: bool
    uploaded_at: UtcDateTime | None = None
    download_url: str


class AppReleaseMainsPublic(BaseModel):
    android: AppReleasePublic | None = None
    ios: AppReleasePublic | None = None


class AppDownloadRecordResult(BaseModel):
    platform: AppPlatform
    version: str
    release_id: str
    download_url: str
    user_type: Literal["customer", "seller"]


class AppReleaseDeleteResult(BaseModel):
    id: str
    message: str = Field(default="Build eliminado.")
