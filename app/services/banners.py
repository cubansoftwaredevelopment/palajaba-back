from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status, UploadFile

from app.database import get_marketplace_banners_collection
from app.schemas.banners import BannerAdminPublic, BannerPublic, BannerUpdate
from app.services.cuba_locations import PROVINCE_NAMES
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


def _document_to_admin(doc: dict[str, Any]) -> BannerAdminPublic:
    return BannerAdminPublic(
        id=str(doc["_id"]),
        image_url=doc["image_url"],
        title=doc.get("title"),
        link_url=doc.get("link_url"),
        province_ids=list(doc.get("province_ids") or []),
        sort_order=int(doc.get("sort_order", 0)),
        is_active=bool(doc.get("is_active", True)),
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


async def list_admin_banners() -> list[BannerAdminPublic]:
    collection = get_marketplace_banners_collection()
    docs = await collection.find({}).sort(
        [("sort_order", 1), ("created_at", -1)]
    ).to_list(length=None)
    return [_document_to_admin(doc) for doc in docs]


async def list_public_banners(province_id: str | None = None) -> list[BannerPublic]:
    collection = get_marketplace_banners_collection()
    query: dict[str, Any] = {"is_active": True}
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
        "created_at": now,
        "updated_at": now,
    }
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _document_to_admin(doc)


async def update_banner(banner_id: str, payload: BannerUpdate) -> BannerAdminPublic:
    doc = await _get_banner_or_404(banner_id)
    collection = get_marketplace_banners_collection()
    updates: dict[str, Any] = {"updated_at": to_utc_naive(utc_now())}

    if payload.title is not None:
        updates["title"] = payload.title.strip() or None
    if payload.link_url is not None:
        updates["link_url"] = payload.link_url.strip() or None
    if payload.province_ids is not None:
        updates["province_ids"] = _normalize_province_ids(payload.province_ids)
    if payload.is_active is not None:
        updates["is_active"] = bool(payload.is_active)
    if payload.sort_order is not None:
        updates["sort_order"] = int(payload.sort_order)

    if len(updates) == 1:
        return _document_to_admin(doc)

    object_id = doc["_id"]
    await collection.update_one({"_id": object_id}, {"$set": updates})
    updated = await collection.find_one({"_id": object_id})
    assert updated is not None
    return _document_to_admin(updated)


async def delete_banner(banner_id: str) -> dict[str, Any]:
    doc = await _get_banner_or_404(banner_id)
    object_id = doc["_id"]
    await remove_image(doc.get("image_url"), public_id=doc.get("public_id"))
    await get_marketplace_banners_collection().delete_one({"_id": object_id})
    return {"id": str(object_id), "message": "Banner eliminado."}