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
