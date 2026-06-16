from pydantic import BaseModel


class AdminStatsSummary(BaseModel):
    year: int
    month: int
    payments_total_cup: int
    payments_count: int
    active_stores: int
    pending_registrations: int
    published_products: int
    orders_total: int


class AdminProvinceBusinessCount(BaseModel):
    province_id: str
    province_name: str
    count: int


class AdminBusinessesByProvince(BaseModel):
    total_with_location: int
    without_location: int
    provinces: list[AdminProvinceBusinessCount]
