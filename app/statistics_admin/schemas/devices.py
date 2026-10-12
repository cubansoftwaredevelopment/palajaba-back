from typing import Literal

from pydantic import BaseModel, Field

from app.statistics_admin.schemas.traffic import TrafficDataPoint

DevicePlatform = Literal["android", "ios"]
SessionKind = Literal["seller", "gestor"]


class DevicePresenceRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=64)
    platform: DevicePlatform
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    session_kind: SessionKind | None = None


class DevicePresenceResult(BaseModel):
    ok: bool = True


class DeviceMapMarker(BaseModel):
    lat: float
    lng: float
    signed_in: bool = False
    session_kind: SessionKind | None = None
    active: bool = False


class AdminDeviceStats(BaseModel):
    registered: int = 0
    active_now: int = 0
    signed_in_now: int = 0
    live: bool = True
    map_day: str | None = None
    points: list[TrafficDataPoint] = Field(default_factory=list)
    markers: list[DeviceMapMarker] = Field(default_factory=list)
