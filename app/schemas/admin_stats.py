from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.seller_stats import PeriodComparison, RevenueDataPoint


class AdminStatsSummary(BaseModel):
    year: int
    month: int
    payments_total_cup: int
    payments_count: int
    active_stores: int
    pending_registrations: int
    published_products: int
    orders_total: int
    marketplace_visits: int = 0


class AdminProvinceBusinessCount(BaseModel):
    province_id: str
    province_name: str
    count: int


class AdminBusinessesByProvince(BaseModel):
    total_with_location: int
    without_location: int
    provinces: list[AdminProvinceBusinessCount]


class AdminRevenueChart(BaseModel):
    granularity: Literal["daily", "weekly", "monthly"]
    year: int | None = None
    month: int | None = None
    months_available: int
    total_cup: int = 0
    payments_count: int = 0
    points: list[RevenueDataPoint] = Field(default_factory=list)
    comparison: PeriodComparison | None = None
