"""Esquemas de las estadísticas del admin, el tráfico y los dispositivos."""

from app.statistics_admin.schemas.devices import (
    AdminDeviceStats,
    DeviceMapMarker,
    DevicePresenceRequest,
    DevicePresenceResult,
)
from app.statistics_admin.schemas.orders import (
    AdminOrdersByLocation,
    AdminOrdersChart,
    AdminOrdersLocationItem,
    AdminSalesChart,
    AdminTopBusinessItem,
    AdminTopBusinesses,
    AdminTopPopularProduct,
    AdminTopPopularProducts,
    AdminTopSoldProduct,
    AdminTopSoldProducts,
    OrdersGranularity,
)
from app.statistics_admin.schemas.stats import (
    AdminBusinessesByProvince,
    AdminProvinceBusinessCount,
    AdminRevenueChart,
    AdminStatsSummary,
)
from app.statistics_admin.schemas.traffic import (
    AdminTrafficByLocation,
    AdminTrafficChart,
    AdminTrafficLocationItem,
    AdminTrafficPatterns,
    MarketplaceVisitRecordResult,
    MarketplaceVisitRequest,
    TrafficDataPoint,
    TrafficGranularity,
)

__all__ = [
    "AdminBusinessesByProvince",
    "AdminDeviceStats",
    "AdminOrdersByLocation",
    "AdminOrdersChart",
    "AdminOrdersLocationItem",
    "AdminProvinceBusinessCount",
    "AdminRevenueChart",
    "AdminSalesChart",
    "AdminStatsSummary",
    "AdminTopBusinessItem",
    "AdminTopBusinesses",
    "AdminTopPopularProduct",
    "AdminTopPopularProducts",
    "AdminTopSoldProduct",
    "AdminTopSoldProducts",
    "AdminTrafficByLocation",
    "AdminTrafficChart",
    "AdminTrafficLocationItem",
    "AdminTrafficPatterns",
    "DeviceMapMarker",
    "DevicePresenceRequest",
    "DevicePresenceResult",
    "MarketplaceVisitRecordResult",
    "MarketplaceVisitRequest",
    "OrdersGranularity",
    "TrafficDataPoint",
    "TrafficGranularity",
]
