from typing import Literal

from pydantic import BaseModel, Field


class SeriesPoint(BaseModel):
    key: str
    label: str
    value: float


class CurrencyTotal(BaseModel):
    currency: str
    total: float


class SellerStatsKpis(BaseModel):
    visitors: int
    product_views: int
    delivered_orders: int
    revenue: list[CurrencyTotal]
    delivery: list[CurrencyTotal] = Field(default_factory=list)
    site_jabas: int
    site_conversion_rate: float


class SiteConversion(BaseModel):
    visitors: int
    jabas: int
    rate: float


class ProductConversionItem(BaseModel):
    product_id: str
    name: str
    image_url: str | None = None
    views: int
    purchases: int
    conversion_rate: float


class ProductConversion(BaseModel):
    items: list[ProductConversionItem]
    global_conversion_rate: float
    total_views: int
    total_purchases: int


class HighViewsLowSales(BaseModel):
    items: list[ProductConversionItem]


class ZoneView(BaseModel):
    province_id: str
    province_name: str
    municipality_id: str
    municipality_name: str
    views: int


class ViewsByZone(BaseModel):
    items: list[ZoneView]


class SeriesChart(BaseModel):
    total: float
    points: list[SeriesPoint]


class RevenueSeries(BaseModel):
    currency: str
    total: float
    points: list[SeriesPoint]


class RevenueChart(BaseModel):
    series: list[RevenueSeries]
    delivery_series: list[RevenueSeries] = Field(default_factory=list)


class TopSoldItem(BaseModel):
    product_id: str
    name: str
    image_url: str | None = None
    units_sold: int = Field(ge=0)


class TopSold(BaseModel):
    items: list[TopSoldItem]


class SellerStatsPeriod(BaseModel):
    earliest_year: int
    earliest_month: int
    current_year: int
    current_month: int
    months_available: int


class SellerStatsSummary(BaseModel):
    year: int
    month: int
    profile_views: int
    confirmed_orders: int
    active_products: int
    period: SellerStatsPeriod


class RevenueDataPoint(BaseModel):
    key: str
    label: str
    amount: float
    time: int = 0
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0


class PeriodComparison(BaseModel):
    current_total: float = 0.0
    previous_total: float = 0.0
    change_percent: float | None = None
    comparison_available: bool = True
    period_label: str = ""
    previous_period_label: str = ""
    comparison_label: str = ""
    direction: Literal["up", "down", "flat", "unavailable"] = "unavailable"


class CurrencyRevenueSeries(BaseModel):
    currency: str
    total: float
    points: list[RevenueDataPoint] = Field(default_factory=list)
    comparison: PeriodComparison | None = None


class SellerRevenueChart(BaseModel):
    granularity: str
    year: int | None = None
    month: int | None = None
    months_available: int
    series: list[CurrencyRevenueSeries] = Field(default_factory=list)
    delivery_series: list[CurrencyRevenueSeries] = Field(default_factory=list)


class ProductsSoldDataPoint(BaseModel):
    key: str
    label: str
    count: int


class SellerProductsSoldChart(BaseModel):
    granularity: str
    year: int | None = None
    month: int | None = None
    months_available: int
    total: int
    points: list[ProductsSoldDataPoint] = Field(default_factory=list)
    comparison: PeriodComparison | None = None


class SellerTopProductItem(BaseModel):
    product_id: str
    name: str
    image_url: str | None = None
    popularity: int | None = None
    units_sold: int | None = None


class SellerTopProducts(BaseModel):
    most_popular: list[SellerTopProductItem] = Field(default_factory=list)
    most_sold: list[SellerTopProductItem] = Field(default_factory=list)
