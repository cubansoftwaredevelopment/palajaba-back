import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo, get_registrations_collection
from app.services.admin_stats import _month_bounds, get_stats_summary


async def main() -> None:
    await connect_to_mongo()
    col = get_registrations_collection()
    doc = await col.find_one({})
    if doc:
        print("Document:", {k: doc.get(k) for k in [
            "store_name", "status", "approved_at", "payment_amount_cup", "subscription_ends_at"
        ]})

    now = datetime.now(UTC)
    start, end = _month_bounds(now.year, now.month)
    print("now:", now)
    print("month:", start, "->", end)

    q_aware = {"status": "approved", "subscription_ends_at": {"$gt": now}}
    q_naive = {"status": "approved", "subscription_ends_at": {"$gt": now.replace(tzinfo=None)}}
    print("active (aware now):", await col.count_documents(q_aware))
    print("active (naive now):", await col.count_documents(q_naive))

    q_pay = {
        "status": "approved",
        "approved_at": {"$gte": start, "$lt": end},
        "payment_amount_cup": {"$ne": None},
    }
    print("payments in month (aware bounds):", await col.count_documents(q_pay))

    q_approved_month = {
        "status": "approved",
        "approved_at": {"$gte": start, "$lt": end},
    }
    print("approved this month (no payment filter):", await col.count_documents(q_approved_month))

    stats = await get_stats_summary(now.year, now.month)
    print("stats:", stats.model_dump())

    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
