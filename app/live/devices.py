from bson import ObjectId
from pymongo import ASCENDING

from app.database import (
    get_app_push_devices_collection,
    get_customer_devices_collection,
    get_seller_devices_collection,
)
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


async def register_customer_device(customer_id: str, payload) -> None:
    collection = get_customer_devices_collection()
    await collection.create_index("token", unique=True)
    await collection.create_index("customer_id")
    await collection.update_one(
        {"token": payload.token},
        {"$set": {"customer_id": ObjectId(customer_id), "token": payload.token,
                  "platform": payload.platform, "updated_at": to_utc_naive(utc_now())}},
        upsert=True,
    )


async def delete_customer_device(customer_id: str, token: str) -> None:
    await get_customer_devices_collection().delete_one(
        {"customer_id": ObjectId(customer_id), "token": token}
    )


async def list_customer_device_tokens(customer_id: str) -> list[str]:
    docs = await get_customer_devices_collection().find(
        {"customer_id": ObjectId(customer_id)}, {"token": 1}
    ).to_list(length=50)
    return [str(doc["token"]) for doc in docs if doc.get("token")]


async def register_app_push_device(*, token: str, platform: str) -> dict[str, str]:
    """Registra token FCM de la app instalada, con o sin sesión."""
    normalized = str(platform or "").strip().lower()
    clean_token = str(token or "").strip()
    if normalized not in ("android", "ios") or len(clean_token) < 8:
        raise ValueError("Dispositivo no válido.")
    now = to_utc_naive(utc_now())
    await get_app_push_devices_collection().update_one(
        {"token": clean_token},
        {
            "$set": {
                "token": clean_token,
                "platform": normalized,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {"token": clean_token, "platform": normalized}


async def list_device_tokens_for_platform(platform: str) -> list[str]:
    """Tokens FCM de la app nativa + cuentas en una plataforma (android|ios)."""
    normalized = str(platform or "").strip().lower()
    if normalized not in ("android", "ios"):
        return []
    query = {"platform": normalized}
    app_docs = await get_app_push_devices_collection().find(query, {"token": 1}).to_list(
        length=10000
    )
    seller_docs = await get_seller_devices_collection().find(query, {"token": 1}).to_list(
        length=5000
    )
    customer_docs = await get_customer_devices_collection().find(
        query, {"token": 1}
    ).to_list(length=5000)
    tokens: list[str] = []
    seen: set[str] = set()
    for doc in (*app_docs, *seller_docs, *customer_docs):
        token = str(doc.get("token") or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens
