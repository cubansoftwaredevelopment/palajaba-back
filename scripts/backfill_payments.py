"""
Asigna monto de plan a tiendas aprobadas sin payment_amount_cup.

Uso (desde backend):
  .\\venv\\Scripts\\python.exe scripts\\backfill_payments.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo, get_registrations_collection
from app.services.plans import normalize_plan_tier, plan_price_cup


async def main() -> None:
    await connect_to_mongo()
    collection = get_registrations_collection()

    cursor = collection.find(
        {"status": "approved", "$or": [{"payment_amount_cup": None}, {"payment_amount_cup": {"$exists": False}}]}
    )
    updated = 0
    async for doc in cursor:
        amount = plan_price_cup(
            normalize_plan_tier(doc.get("plan_tier")),
            doc.get("billing_period") or "monthly",
        )
        await collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"payment_amount_cup": amount}},
        )
        print(f"  {doc.get('store_name')}: {amount} CUP")
        updated += 1

    await close_mongo_connection()
    print(f"Listo. {updated} tienda(s) actualizada(s).")


if __name__ == "__main__":
    asyncio.run(main())
