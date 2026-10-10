from bson import ObjectId
from pymongo import ASCENDING

from app.database import get_seller_devices_collection
from app.live.schemas.device import SellerDevicePublic, SellerDeviceRegister
from app.utils.datetime import to_utc_naive, utc_now


async def ensure_seller_device_indexes() -> None:
    collection = get_seller_devices_collection()
    await collection.create_index([("token", ASCENDING)], unique=True)
    await collection.create_index([("seller_id", ASCENDING)])


async def register_seller_device(seller_id: str, payload: SellerDeviceRegister) -> SellerDevicePublic:
    await ensure_seller_device_indexes()
    now = to_utc_naive(utc_now())
    collection = get_seller_devices_collection()
    await collection.update_one(
        {"token": payload.token},
        {
            "$set": {
                "seller_id": ObjectId(seller_id),
                "token": payload.token,
                "platform": payload.platform,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return SellerDevicePublic(token=payload.token, platform=payload.platform, updated_at=now)


async def delete_seller_device(seller_id: str, token: str) -> None:
    collection = get_seller_devices_collection()
    await collection.delete_one({"seller_id": ObjectId(seller_id), "token": token})


async def list_seller_device_tokens(seller_id: str) -> list[str]:
    collection = get_seller_devices_collection()
    cursor = collection.find({"seller_id": ObjectId(seller_id)}, {"token": 1})
    docs = await cursor.to_list(length=50)
    return [str(doc["token"]) for doc in docs if doc.get("token")]
