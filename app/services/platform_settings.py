from typing import Any

from fastapi import HTTPException, status

from app.database import get_platform_settings_collection
from app.schemas.platform_settings import PlatformSettingsPublic, PlatformSettingsUpdate
from app.utils.datetime import to_utc_naive, utc_now

SETTINGS_ID = "global"


def _document_to_public(doc: dict[str, Any] | None) -> PlatformSettingsPublic:
    if not doc:
        return PlatformSettingsPublic()
    phone = doc.get("renewal_contact_phone")
    return PlatformSettingsPublic(
        renewal_contact_phone=phone if isinstance(phone, str) and phone else None,
    )


async def ensure_platform_settings_indexes() -> None:
    collection = get_platform_settings_collection()
    await collection.create_index("_id")


async def get_platform_settings() -> PlatformSettingsPublic:
    collection = get_platform_settings_collection()
    doc = await collection.find_one({"_id": SETTINGS_ID})
    return _document_to_public(doc)


async def get_renewal_contact_phone() -> str | None:
    settings = await get_platform_settings()
    return settings.renewal_contact_phone


async def update_platform_settings(payload: PlatformSettingsUpdate) -> PlatformSettingsPublic:
    now = to_utc_naive(utc_now())
    collection = get_platform_settings_collection()
    await collection.update_one(
        {"_id": SETTINGS_ID},
        {
            "$set": {
                "renewal_contact_phone": payload.renewal_contact_phone,
                "updated_at": now,
            },
            "$setOnInsert": {
                "_id": SETTINGS_ID,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return await get_platform_settings()


async def require_renewal_contact_phone() -> str:
    phone = await get_renewal_contact_phone()
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El administrador aún no configuró un teléfono para renovaciones.",
        )
    return phone
