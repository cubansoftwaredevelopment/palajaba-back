from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MensajeroCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=8, max_length=20)
    username: str = Field(min_length=2, max_length=32)


class MensajeroPublic(BaseModel):
    id: str
    seller_id: str
    first_name: str
    last_name: str
    phone: str
    username: str
    has_password: bool
    profile_photo_url: str | None = None
    qvapay_username: str | None = None
    qvapay_verified: bool = False
    vehicle_types: list[str] = []
    vehicles: list[dict] = []
    is_active: bool = True
    updated_at: str | None = None
    section_updated_at: dict[str, str] = Field(default_factory=dict)


class AssignmentFee(BaseModel):
    order_id: str
    pay_via: str = Field(pattern="^(qvapay|other)$")
    fee_amount: float = Field(ge=0)
    fee_currency: str


class AssignBatchRequest(BaseModel):
    client_id: str | None = None
    mensajero_id: str
    orders: list[AssignmentFee] = Field(min_length=1)


class MensajeroLoginRequest(BaseModel):
    username: str
    password: str | None = None


class MensajeroSetupRequest(BaseModel):
    setup_token: str
    password: str = Field(min_length=6, max_length=128)


class VehicleCreate(BaseModel):
    vehicle_type: str
    plate: str = Field(min_length=1)


class EvidenceRequest(BaseModel):
    client_id: str | None = None
    note: str = ""


class TelemetryPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str | None = None
    lat: float | None = None
    lng: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy: float | None = None
    recorded_at: datetime | None = None
    time: float | None = None

    @model_validator(mode="after")
    def normalize_native_fix(self):
        if self.lat is None and self.latitude is not None:
            self.lat = float(self.latitude)
        if self.lng is None and self.longitude is not None:
            self.lng = float(self.longitude)
        if self.lat is None or self.lng is None:
            raise ValueError("Falta la ubicación.")
        if self.recorded_at is None and self.time:
            self.recorded_at = datetime.fromtimestamp(self.time / 1000, tz=timezone.utc)
        if not self.client_id:
            stamp = int(self.time) if self.time else int((self.recorded_at or datetime.now(timezone.utc)).timestamp() * 1000)
            self.client_id = f"loc-{stamp}-{self.lat:.5f}-{self.lng:.5f}"
        return self


class StartRouteRequest(BaseModel):
    client_id: str | None = None
    vehicle_id: str


class CustomerLocationRequest(BaseModel):
    lat: float
    lng: float


class DeviceRegister(BaseModel):
    token: str = Field(min_length=8)
    platform: str
