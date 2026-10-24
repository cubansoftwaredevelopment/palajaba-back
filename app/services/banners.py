from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status, UploadFile

from app.database import get_marketplace_banners_collection
from app.schemas.banners import BannerAdminPublic, BannerPublic, BannerUpdate
from app.constants import PROVINCE_NAMES
from app.services.media_storage import read_image_upload, remove_image, store_image
from app.utils.datetime import to_utc_naive, utc_now


def _object_id_or_404(banner_id: str) -> ObjectId:
    try:
        return ObjectId(banner_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Banner no encontrado.",
        ) from exc


async def ensure_banner_indexes() -> None:
    collection = get_marketplace_banners_collection()
    await collection.create_index([("is_active", 1), ("sort_order", 1), ("created_at", 1)])
    await collection.create_index([("is_active", 1), ("deactivate_at", 1)])


def _document_to_admin(doc: dict[str, Any]) -> BannerAdminPublic:
    return BannerAdminPublic(
        id=str(doc["_id"]),
        image_url=doc["image_url"],
        title=doc.get("title"),
        link_url=doc.get("link_url"),
        province_ids=list(doc.get("province_ids") or []),
        sort_order=int(doc.get("sort_order", 0)),
        is_active=bool(doc.get("is_active", True)),
        deactivate_at=doc.get("deactivate_at"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


def _document_to_public(doc: dict[str, Any]) -> BannerPublic:
    return BannerPublic(
        id=str(doc["_id"]),
        image_url=doc["image_url"],
        title=doc.get("title"),
        link_url=doc.get("link_url"),
        province_ids=list(doc.get("province_ids") or []),
        sort_order=int(doc.get("sort_order", 0)),
    )


def _normalize_province_ids(province_ids: list[str] | None) -> list[str]:
    if not province_ids:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for province_id in province_ids:
        normalized = str(province_id).strip()
        if not normalized or normalized in seen:
            continue
        if normalized not in PROVINCE_NAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Provincia no válida: {normalized}.",
            )
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _parse_deactivate_at(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La fecha de inactivación no es válida.",
            ) from exc
    else:
        parsed = value
    moment = to_utc_naive(parsed)
    if moment <= to_utc_naive(utc_now()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de expiración debe ser mayor que la actual.",
        )
    return moment


async def expire_due_banners() -> None:
    now = to_utc_naive(utc_now())
    await get_marketplace_banners_collection().update_many(
        {"is_active": True, "deactivate_at": {"$lte": now}},
        {"$set": {"is_active": False, "updated_at": now}},
    )


async def list_admin_banners() -> list[BannerAdminPublic]:
    await expire_due_banners()
    collection = get_marketplace_banners_collection()
    docs = await collection.find({}).sort(
        [("sort_order", 1), ("created_at", -1)]
    ).to_list(length=None)
    return [_document_to_admin(doc) for doc in docs]


async def list_public_banners(province_id: str | None = None) -> list[BannerPublic]:
    await expire_due_banners()
    collection = get_marketplace_banners_collection()
    now = to_utc_naive(utc_now())
    query: dict[str, Any] = {
        "is_active": True,
        "$and": [
            {
                "$or": [
                    {"deactivate_at": {"$exists": False}},
                    {"deactivate_at": None},
                    {"deactivate_at": {"$gt": now}},
                ]
            }
        ],
    }
    normalized_province = str(province_id or "").strip() or None
    if normalized_province:
        query["$or"] = [
            {"province_ids": {"$exists": False}},
            {"province_ids": {"$size": 0}},
            {"province_ids": normalized_province},
        ]
    docs = await collection.find(query).sort(
        [("sort_order", 1), ("created_at", -1)]
    ).to_list(length=None)
    return [_document_to_public(doc) for doc in docs]


async def _get_banner_or_404(banner_id: str) -> dict[str, Any]:
    object_id = _object_id_or_404(banner_id)
    doc = await get_marketplace_banners_collection().find_one({"_id": object_id})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Banner no encontrado.",
        )
    return doc


async def create_banner(
    file: UploadFile,
    *,
    admin_id: str,
    title: str | None = None,
    link_url: str | None = None,
    province_ids: list[str] | None = None,
    deactivate_at: datetime | str | None = None,
) -> BannerAdminPublic:
    content, content_type = await read_image_upload(file)
    stored = await store_image(
        content,
        content_type,
        scope="banners",
        owner_id=admin_id or "admin",
    )

    collection = get_marketplace_banners_collection()
    now = to_utc_naive(utc_now())
    doc = {
        "image_url": stored.url,
        "public_id": stored.public_id,
        "title": (title or "").strip() or None,
        "link_url": (link_url or "").strip() or None,
        "province_ids": _normalize_province_ids(province_ids),
        "sort_order": 0,
        "is_active": True,
        "deactivate_at": _parse_deactivate_at(deactivate_at),
        "created_at": now,
        "updated_at": now,
    }
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _document_to_admin(doc)


async def update_banner(banner_id: str, payload: BannerUpdate) -> BannerAdminPublic:
    doc = await _get_banner_or_404(banner_id)
    collection = get_marketplace_banners_collection()
    now = to_utc_naive(utc_now())
    updates: dict[str, Any] = {"updated_at": now}
    fields = payload.model_dump(exclude_unset=True)

    if "title" in fields:
        updates["title"] = (payload.title or "").strip() or None
    if "link_url" in fields:
        updates["link_url"] = (payload.link_url or "").strip() or None
    if "province_ids" in fields:
        updates["province_ids"] = _normalize_province_ids(payload.province_ids)
    if "deactivate_at" in fields:
        scheduled = _parse_deactivate_at(payload.deactivate_at)
        updates["deactivate_at"] = scheduled
        if scheduled is not None and "is_active" not in fields:
            updates["is_active"] = True
    if "is_active" in fields:
        updates["is_active"] = bool(payload.is_active)
        if payload.is_active and "deactivate_at" not in fields:
            existing = doc.get("deactivate_at")
            if isinstance(existing, datetime) and to_utc_naive(existing) <= now:
                updates["deactivate_at"] = None
    if "sort_order" in fields and payload.sort_order is not None:
        updates["sort_order"] = int(payload.sort_order)

    if len(updates) == 1:
        return _document_to_admin(doc)

    object_id = doc["_id"]
    await collection.update_one({"_id": object_id}, {"$set": updates})
    updated = await collection.find_one({"_id": object_id})
    assert updated is not None
    return _document_to_admin(updated)


async def replace_banner_image(
    banner_id: str,
    file: UploadFile,
    *,
    admin_id: str,
) -> BannerAdminPublic:
    doc = await _get_banner_or_404(banner_id)
    content, content_type = await read_image_upload(file)
    stored = await store_image(
        content,
        content_type,
        scope="banners",
        owner_id=admin_id or "admin",
    )
    await remove_image(doc.get("image_url"), public_id=doc.get("public_id"))
    now = to_utc_naive(utc_now())
    await get_marketplace_banners_collection().update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "image_url": stored.url,
                "public_id": stored.public_id,
                "updated_at": now,
            }
        },
    )
    updated = await get_marketplace_banners_collection().find_one({"_id": doc["_id"]})
    assert updated is not None
    return _document_to_admin(updated)


async def delete_banner(banner_id: str) -> dict[str, Any]:
    doc = await _get_banner_or_404(banner_id)
    object_id = doc["_id"]
    await remove_image(doc.get("image_url"), public_id=doc.get("public_id"))
    await get_marketplace_banners_collection().delete_one({"_id": object_id})
    return {"id": str(object_id), "message": "Banner eliminado."}