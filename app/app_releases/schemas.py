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
    download_count: int = 0


class AppReleaseMainsPublic(BaseModel):
    android: AppReleasePublic | None = None
    ios: AppReleasePublic | None = None


class AppDownloadRecordResult(BaseModel):
    platform: AppPlatform
    version: str
    release_id: str
    download_url: str
    user_type: Literal["customer", "seller"]


class AppInstalledSyncRequest(BaseModel):
    platform: AppPlatform
    version: str = Field(min_length=1, max_length=40)
    device_id: str | None = Field(default=None, min_length=8, max_length=64)


class AppInstalledSyncResult(BaseModel):
    platform: AppPlatform
    version: str
    release_id: str | None = None
    download_url: str | None = None
    recorded: bool = False
    counted: bool = False
    user_type: Literal["customer", "seller"]


class AppPlatformPromptStatus(BaseModel):
    main: AppReleasePublic | None = None
    downloaded_version: str | None = None
    needs_download: bool = False


class AppReleasePromptStatus(BaseModel):
    android: AppPlatformPromptStatus
    ios: AppPlatformPromptStatus


class AppReleaseDeleteResult(BaseModel):
    id: str
    message: str = Field(default="Build eliminado.")
