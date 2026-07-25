from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.seller_stats import PeriodComparison

TrafficPage = Literal["marketplace"]
TrafficGranularity = Literal["daily", "weekly", "monthly"]


class MarketplaceVisitRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    page: TrafficPage = "marketplace"
    province_id: str = Field(..., min_length=1, max_length=80)
    municipality_id: str = Field(..., min_length=1, max_length=80)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("session_id vacío")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        if any(ch not in allowed for ch in cleaned):
            raise ValueError("session_id inválido")
        return cleaned

    @field_validator("province_id", "municipality_id")
    @classmethod
    def strip_ids(cls, value: str) -> str:
        return value.strip()


class MarketplaceVisitRecordResult(BaseModel):
    recorded: bool
    duplicate: bool = False


class TrafficDataPoint(BaseModel):
    key: str
    label: str
    count: int


class AdminTrafficChart(BaseModel):
    granularity: TrafficGranularity
    year: int | None = None
    month: int | None = None
    months_available: int
    total_visits: int = 0
    points: list[TrafficDataPoint] = Field(default_factory=list)
    comparison: PeriodComparison | None = None


class AdminTrafficLocationItem(BaseModel):
    province_id: str
    province_name: str
    municipality_id: str | None = None
    municipality_name: str | None = None
    count: int


class AdminTrafficByLocation(BaseModel):
    year: int
    month: int
    total_visits: int
    provinces: list[AdminTrafficLocationItem] = Field(default_factory=list)
    municipalities: list[AdminTrafficLocationItem] = Field(default_factory=list)


class AdminTrafficPatterns(BaseModel):
    year: int
    month: int
    total_visits: int
    by_hour: list[TrafficDataPoint] = Field(default_factory=list)
    by_weekday: list[TrafficDataPoint] = Field(default_factory=list)
