from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.marketplace_traffic import TrafficDataPoint
from app.schemas.seller_stats import PeriodComparison

OrdersGranularity = Literal["daily", "weekly", "monthly"]


class AdminOrdersChart(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    months_available: int
    total_orders: int = 0
    points: list[TrafficDataPoint] = Field(default_factory=list)
    comparison: PeriodComparison | None = None


class AdminTopBusinessItem(BaseModel):
    seller_id: str
    store_name: str
    store_slug: str | None = None
    count: int
    province_name: str | None = None
    municipality_name: str | None = None


class AdminTopBusinesses(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    period_label: str
    total_orders: int = 0
    businesses: list[AdminTopBusinessItem] = Field(default_factory=list)


class AdminOrdersLocationItem(BaseModel):
    province_id: str
    province_name: str
    municipality_id: str | None = None
    municipality_name: str | None = None
    count: int


class AdminOrdersByLocation(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    period_label: str
    total_orders: int = 0
    without_location: int = 0
    provinces: list[AdminOrdersLocationItem] = Field(default_factory=list)
    municipalities: list[AdminOrdersLocationItem] = Field(default_factory=list)
