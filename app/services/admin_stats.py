from app.database import (
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.schemas.admin_stats import (
    AdminBusinessesByProvince,
    AdminProvinceBusinessCount,
    AdminStatsSummary,
)
from app.services.cuba_locations import PROVINCE_NAMES
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.month_bounds import month_bounds


async def get_stats_summary(year: int, month: int) -> AdminStatsSummary:
    collection = get_registrations_collection()
    start, end = month_bounds(year, month)
    now = to_utc_naive(utc_now())

    payments_pipeline = [
        {
            "$match": {
                "status": "approved",
                "approved_at": {"$gte": start, "$lt": end},
                "payment_amount_cup": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$payment_amount_cup"},
                "count": {"$sum": 1},
            }
        },
    ]
    payments_result = await collection.aggregate(payments_pipeline).to_list(length=1)
    payments_total = int(payments_result[0]["total"]) if payments_result else 0
    payments_count = int(payments_result[0]["count"]) if payments_result else 0

    active_stores = await collection.count_documents(
        {
            "status": "approved",
            "subscription_ends_at": {"$gt": now},
        }
    )
    pending_registrations = await collection.count_documents({"status": "pending"})

    published_products = await get_catalog_products_collection().count_documents({})
    orders_total = await get_orders_collection().count_documents({})

    return AdminStatsSummary(
        year=year,
        month=month,
        payments_total_cup=payments_total,
        payments_count=payments_count,
        active_stores=active_stores,
        pending_registrations=pending_registrations,
        published_products=published_products,
        orders_total=orders_total,
    )


async def get_businesses_by_province() -> AdminBusinessesByProvince:
    collection = get_registrations_collection()

    pipeline = [
        {"$match": {"status": "approved", "business_area.province_id": {"$exists": True, "$ne": ""}}},
        {
            "$group": {
                "_id": "$business_area.province_id",
                "province_name": {"$first": "$business_area.province_name"},
                "count": {"$sum": 1},
            }
        },
    ]
    grouped = await collection.aggregate(pipeline).to_list(length=None)
    counts_by_id = {row["_id"]: int(row["count"]) for row in grouped}

    provinces: list[AdminProvinceBusinessCount] = []
    for province_id, province_name in PROVINCE_NAMES.items():
        count = counts_by_id.get(province_id, 0)
        if count > 0:
            provinces.append(
                AdminProvinceBusinessCount(
                    province_id=province_id,
                    province_name=province_name,
                    count=count,
                )
            )

    provinces.sort(key=lambda item: (-item.count, item.province_name))

    without_location = await collection.count_documents(
        {
            "status": "approved",
            "$or": [
                {"business_area": {"$exists": False}},
                {"business_area.province_id": {"$exists": False}},
                {"business_area.province_id": ""},
            ],
        }
    )
    total_with_location = sum(item.count for item in provinces)

    return AdminBusinessesByProvince(
        total_with_location=total_with_location,
        without_location=without_location,
        provinces=provinces,
    )
