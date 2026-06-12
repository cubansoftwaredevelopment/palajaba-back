from pydantic import BaseModel, Field


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


class CurrencyRevenueSeries(BaseModel):
    currency: str
    total: float
    points: list[RevenueDataPoint] = Field(default_factory=list)


class SellerRevenueChart(BaseModel):
    granularity: str
    year: int | None = None
    month: int | None = None
    months_available: int
    series: list[CurrencyRevenueSeries] = Field(default_factory=list)


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


class SellerTopProductItem(BaseModel):
    product_id: str
    name: str
    image_url: str | None = None
    popularity: int | None = None
    units_sold: int | None = None


class SellerTopProducts(BaseModel):
    most_popular: list[SellerTopProductItem] = Field(default_factory=list)
    most_sold: list[SellerTopProductItem] = Field(default_factory=list)
