import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo, get_registrations_collection


async def main() -> None:
    await connect_to_mongo()
    collection = get_registrations_collection()
    count = await collection.count_documents({})
    print(f"Total registrations: {count}")
    async for doc in collection.find().sort("created_at", -1):
        print(
            f"  - {doc.get('store_name')} | {doc.get('status')} | "
            f"{doc.get('transfer_id')} | {doc.get('phone')}"
        )
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
