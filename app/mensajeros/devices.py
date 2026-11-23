from bson import ObjectId
from pymongo import ASCENDING

from app.database import get_mensajero_devices_collection
from app.utils.datetime import to_utc_naive, utc_now


async def ensure_device_indexes() -> None:
    collection = get_mensajero_devices_collection()
    await collection.create_index([("token", ASCENDING)], unique=True)
    await collection.create_index([("mensajero_id", ASCENDING)])


async def register_device(mensajero_id: str, token: str, platform: str) -> None:
    await ensure_device_indexes()
    now = to_utc_naive(utc_now())
    await get_mensajero_devices_collection().update_one(
        {"token": token},
        {"$set": {
            "mensajero_id": ObjectId(mensajero_id),
            "token": token,
            "platform": platform.strip().lower(),
            "updated_at": now,
        }},
        upsert=True,
    )


async def list_device_tokens(mensajero_id: str) -> list[str]:
    docs = await get_mensajero_devices_collection().find(
        {"mensajero_id": ObjectId(mensajero_id)}, {"token": 1}
    ).to_list(length=20)
    return [str(doc["token"]) for doc in docs if doc.get("token")]
