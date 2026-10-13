from typing import Literal

from pydantic import BaseModel, Field

from app.statistics_admin.schemas.traffic import TrafficDataPoint
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


class AdminSalesChart(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    months_available: int
    total_cup: float = 0
    orders_counted: int = 0
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


class AdminTopSoldProduct(BaseModel):
    product_id: str
    name: str
    store_name: str
    quantity: int
    amount_cup: float | None = None


class AdminTopSoldProducts(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    period_label: str
    total_units: int = 0
    products: list[AdminTopSoldProduct] = Field(default_factory=list)


class AdminTopPopularProduct(BaseModel):
    product_id: str
    name: str
    store_name: str
    points: int
    views: int = 0
    jaba: int = 0
    purchases: int = 0


class AdminTopPopularProducts(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    period_label: str
    total_points: int = 0
    products: list[AdminTopPopularProduct] = Field(default_factory=list)


class AdminDeliveryPin(BaseModel):
    order_id: str
    lat: float
    lng: float
    store_name: str
    address: str | None = None


class AdminDeliveryMap(BaseModel):
    granularity: OrdersGranularity
    year: int | None = None
    month: int | None = None
    period_label: str
    orders_total: int = 0
    delivery_orders: int = 0
    pins: list[AdminDeliveryPin] = Field(default_factory=list)


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
