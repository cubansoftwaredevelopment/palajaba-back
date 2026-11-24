from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    client_id: str
    lat: float
    lng: float
    accuracy: float | None = None
    recorded_at: datetime | None = None


class StartRouteRequest(BaseModel):
    client_id: str | None = None
    vehicle_id: str


class CustomerLocationRequest(BaseModel):
    lat: float
    lng: float


class DeviceRegister(BaseModel):
    token: str = Field(min_length=8)
    platform: str
