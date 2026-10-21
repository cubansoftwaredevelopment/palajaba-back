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


class TopSoldItem(BaseModel):
    product_id: str
    name: str
    image_url: str | None = None
    units_sold: int = Field(ge=0)


class TopSold(BaseModel):
    items: list[TopSoldItem]
