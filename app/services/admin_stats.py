from datetime import UTC, datetime

from app.database import get_registrations_collection
from app.schemas.admin_stats import AdminStatsSummary
from app.utils.datetime import to_utc_naive, utc_now


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return to_utc_naive(start), to_utc_naive(end)


async def get_stats_summary(year: int, month: int) -> AdminStatsSummary:
    collection = get_registrations_collection()
    start, end = _month_bounds(year, month)
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

    return AdminStatsSummary(
        year=year,
        month=month,
        payments_total_cup=payments_total,
        payments_count=payments_count,
        active_stores=active_stores,
        pending_registrations=pending_registrations,
    )
