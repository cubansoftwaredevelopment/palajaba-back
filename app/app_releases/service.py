from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any, Literal
from urllib.parse import quote

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from gridfs.errors import NoFile

from app.app_releases.schemas import (
    AppDownloadRecordResult,
    AppPlatformPromptStatus,
    AppReleaseDeleteResult,
    AppReleaseMainsPublic,
    AppReleasePromptStatus,
    AppReleasePublic,
)
from app.database import (
    get_app_download_records_collection,
    get_app_release_gridfs,
    get_app_releases_collection,
)
from app.utils.datetime import to_utc_naive, utc_now

AppPlatform = Literal["android", "ios"]

MAX_RELEASES_PER_PLATFORM = 5
MAX_APP_BYTES = 200 * 1024 * 1024
GRIDFS_CHUNK_BYTES = 1024 * 1024

_PLATFORM_EXTENSIONS: dict[str, str] = {
    "android": ".apk",
    "ios": ".ipa",
}

_CONTENT_TYPES: dict[str, str] = {
    "android": "application/vnd.android.package-archive",
    "ios": "application/octet-stream",
}


def _object_id_or_404(release_id: str) -> ObjectId:
    try:
        return ObjectId(release_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build no encontrado.",
        ) from exc


def _normalize_version(version: str | None) -> str:
    value = str(version or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica la versión del build.",
        )
    if len(value) > 40:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La versión es demasiado larga.",
        )
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]*", value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La versión no es válida.",
        )
    return value


def _normalize_platform(platform: str | None) -> AppPlatform:
    value = str(platform or "").strip().lower()
    if value not in ("android", "ios"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La plataforma debe ser android o ios.",
        )
    return value  # type: ignore[return-value]


def _download_url(release_id: str) -> str:
    return f"/api/marketplace/app-releases/{release_id}/file"


def _document_to_public(doc: dict[str, Any]) -> AppReleasePublic:
    release_id = str(doc["_id"])
    return AppReleasePublic(
        id=release_id,
        platform=doc["platform"],
        version=doc["version"],
        original_filename=str(doc.get("original_filename") or ""),
        size_bytes=int(doc.get("size_bytes") or 0),
        is_main=bool(doc.get("is_main")),
        uploaded_at=doc.get("uploaded_at"),
        download_url=_download_url(release_id),
        download_count=int(doc.get("download_count") or 0),
    )


async def map_user_app_downloads(
    *,
    user_type: Literal["customer", "seller"],
    user_ids: list[str],
) -> dict[str, list[dict[str, str]]]:
    """Última versión descargada por plataforma, indexada por user_id."""
    ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not ids:
        return {}
    docs = await get_app_download_records_collection().find(
        {"user_type": user_type, "user_id": {"$in": ids}},
        {"user_id": 1, "platform": 1, "version": 1},
    ).to_list(length=len(ids) * 2 + 10)
    result: dict[str, list[dict[str, str]]] = {user_id: [] for user_id in ids}
    for doc in docs:
        user_id = str(doc.get("user_id") or "")
        platform = str(doc.get("platform") or "").strip().lower()
        version = str(doc.get("version") or "").strip()
        if not user_id or platform not in ("android", "ios") or not version:
            continue
        result.setdefault(user_id, []).append({"platform": platform, "version": version})
    for user_id, items in result.items():
        items.sort(key=lambda item: item["platform"])
    return result


async def ensure_app_release_indexes() -> None:
    releases = get_app_releases_collection()
    await releases.create_index([("platform", 1), ("uploaded_at", -1)])
    await releases.create_index(
        [("platform", 1), ("is_main", 1)],
        unique=True,
        partialFilterExpression={"is_main": True},
        name="unique_main_per_platform",
    )
    records = get_app_download_records_collection()
    await records.create_index(
        [("user_type", 1), ("user_id", 1), ("platform", 1)],
        unique=True,
        name="unique_download_per_user_platform",
    )


async def _get_release_or_404(release_id: str) -> dict[str, Any]:
    doc = await get_app_releases_collection().find_one({"_id": _object_id_or_404(release_id)})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build no encontrado.",
        )
    return doc


async def _read_app_upload(file: UploadFile, platform: AppPlatform) -> tuple[bytes, str, str]:
    expected_ext = _PLATFORM_EXTENSIONS[platform]
    filename = str(file.filename or "").strip()
    lower = filename.lower()
    if not lower.endswith(expected_ext):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo debe ser un {expected_ext}.",
        )
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )
    if len(content) > MAX_APP_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El build supera el límite de 200 MB.",
        )
    safe_name = re.sub(r"[^\w.\-]+", "_", filename)[:120] or f"app{expected_ext}"
    return content, safe_name, _CONTENT_TYPES[platform]


async def _store_app_file(
    platform: AppPlatform,
    content: bytes,
    original_filename: str,
    content_type: str,
) -> ObjectId:
    """Guarda el binario en GridFS (persiste en Mongo tras deploys en Render)."""
    ext = _PLATFORM_EXTENSIONS[platform]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    bucket = get_app_release_gridfs()
    return await bucket.upload_from_stream(
        stored_name,
        BytesIO(content),
        metadata={
            "platform": platform,
            "original_filename": original_filename,
            "content_type": content_type,
        },
    )


def _gridfs_id(value: Any) -> ObjectId | None:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except InvalidId:
        return None


async def _delete_release_binary(doc: dict[str, Any]) -> None:
    grid_id = _gridfs_id(doc.get("gridfs_id"))
    if grid_id is None:
        return
    try:
        await get_app_release_gridfs().delete(grid_id)
    except Exception:
        pass


async def _trim_platform_history(platform: AppPlatform) -> None:
    collection = get_app_releases_collection()
    while True:
        docs = await collection.find({"platform": platform}).sort(
            [("uploaded_at", -1)]
        ).to_list(length=None)
        if len(docs) <= MAX_RELEASES_PER_PLATFORM:
            return
        victim = next((doc for doc in reversed(docs) if not doc.get("is_main")), None)
        if victim is None:
            return
        await _delete_release_binary(victim)
        await collection.delete_one({"_id": victim["_id"]})


async def list_admin_releases(platform: str | None = None) -> list[AppReleasePublic]:
    query: dict[str, Any] = {}
    if platform:
        query["platform"] = _normalize_platform(platform)
    docs = await get_app_releases_collection().find(query).sort(
        [("platform", 1), ("uploaded_at", -1)]
    ).to_list(length=None)
    return [_document_to_public(doc) for doc in docs]


async def create_release(
    file: UploadFile,
    *,
    platform: str,
    version: str,
    admin_id: str,
) -> AppReleasePublic:
    normalized_platform = _normalize_platform(platform)
    normalized_version = _normalize_version(version)
    content, original_filename, content_type = await _read_app_upload(file, normalized_platform)
    gridfs_id = await _store_app_file(
        normalized_platform,
        content,
        original_filename,
        content_type,
    )
    now = to_utc_naive(utc_now())
    collection = get_app_releases_collection()
    existing_main = await collection.find_one(
        {"platform": normalized_platform, "is_main": True},
        {"_id": 1},
    )
    doc = {
        "platform": normalized_platform,
        "version": normalized_version,
        "gridfs_id": gridfs_id,
        "original_filename": original_filename,
        "content_type": content_type,
        "size_bytes": len(content),
        "is_main": existing_main is None,
        "download_count": 0,
        "uploaded_at": now,
        "uploaded_by": admin_id or "admin",
    }
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    await _trim_platform_history(normalized_platform)
    refreshed = await collection.find_one({"_id": result.inserted_id})
    assert refreshed is not None
    return _document_to_public(refreshed)


async def set_main_release(release_id: str) -> AppReleasePublic:
    doc = await _get_release_or_404(release_id)
    collection = get_app_releases_collection()
    platform = doc["platform"]
    already_main = bool(doc.get("is_main"))
    if not already_main:
        await collection.update_many(
            {"platform": platform, "is_main": True},
            {"$set": {"is_main": False}},
        )
        await collection.update_one({"_id": doc["_id"]}, {"$set": {"is_main": True}})
    updated = await collection.find_one({"_id": doc["_id"]})
    assert updated is not None
    public = _document_to_public(updated)
    if not already_main:
        try:
            from app.live.push import notify_app_update_devices

            await notify_app_update_devices(
                platform=str(public.platform),
                version=str(public.version),
            )
        except Exception:
            # El main ya quedó marcado aunque falle el push.
            pass
    return public


async def delete_release(release_id: str) -> AppReleaseDeleteResult:
    doc = await _get_release_or_404(release_id)
    if doc.get("is_main"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar el build principal. Marca otro como main primero.",
        )
    await _delete_release_binary(doc)
    await get_app_releases_collection().delete_one({"_id": doc["_id"]})
    return AppReleaseDeleteResult(id=str(doc["_id"]))


async def list_main_releases() -> AppReleaseMainsPublic:
    collection = get_app_releases_collection()
    android = await collection.find_one({"platform": "android", "is_main": True})
    ios = await collection.find_one({"platform": "ios", "is_main": True})
    return AppReleaseMainsPublic(
        android=_document_to_public(android) if android else None,
        ios=_document_to_public(ios) if ios else None,
    )


def _platform_prompt_status(
    main_doc: dict[str, Any] | None,
    record: dict[str, Any] | None,
) -> AppPlatformPromptStatus:
    main = _document_to_public(main_doc) if main_doc else None
    downloaded_version = None
    if record and record.get("version"):
        downloaded_version = str(record["version"]).strip() or None
    needs_download = False
    if main is not None:
        needs_download = (
            downloaded_version is None or downloaded_version != main.version
        )
    return AppPlatformPromptStatus(
        main=main,
        downloaded_version=downloaded_version,
        needs_download=needs_download,
    )


async def get_prompt_status(
    *,
    user_type: Literal["customer", "seller"],
    user_id: str,
) -> AppReleasePromptStatus:
    releases = get_app_releases_collection()
    records = get_app_download_records_collection()
    android_main, ios_main, android_record, ios_record = await asyncio.gather(
        releases.find_one({"platform": "android", "is_main": True}),
        releases.find_one({"platform": "ios", "is_main": True}),
        records.find_one(
            {"user_type": user_type, "user_id": str(user_id), "platform": "android"}
        ),
        records.find_one(
            {"user_type": user_type, "user_id": str(user_id), "platform": "ios"}
        ),
    )
    return AppReleasePromptStatus(
        android=_platform_prompt_status(android_main, android_record),
        ios=_platform_prompt_status(ios_main, ios_record),
    )


async def _iter_gridfs_chunks(grid_out: Any) -> AsyncIterator[bytes]:
    while True:
        chunk = await grid_out.read(GRIDFS_CHUNK_BYTES)
        if not chunk:
            break
        yield chunk


async def stream_release_file(release_id: str) -> StreamingResponse:
    doc = await _get_release_or_404(release_id)
    filename = str(doc.get("original_filename") or "app.bin")
    media_type = str(doc.get("content_type") or "application/octet-stream")
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"

    grid_id = _gridfs_id(doc.get("gridfs_id"))
    if grid_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        )
    try:
        grid_out = await get_app_release_gridfs().open_download_stream(grid_id)
    except NoFile as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        ) from exc
    headers = {"Content-Disposition": disposition}
    length = getattr(grid_out, "length", None)
    if length is None:
        length = doc.get("size_bytes")
    if length is not None:
        headers["Content-Length"] = str(int(length))
    return StreamingResponse(
        _iter_gridfs_chunks(grid_out),
        media_type=media_type,
        headers=headers,
    )


async def record_authenticated_download(
    release_id: str,
    *,
    user_type: Literal["customer", "seller"],
    user_id: str,
) -> AppDownloadRecordResult:
    doc = await _get_release_or_404(release_id)
    now = to_utc_naive(utc_now())
    platform = doc["platform"]
    version = doc["version"]
    release_oid = doc["_id"]
    await get_app_download_records_collection().update_one(
        {
            "user_type": user_type,
            "user_id": str(user_id),
            "platform": platform,
        },
        {
            "$set": {
                "version": version,
                "release_id": str(release_oid),
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )
    await get_app_releases_collection().update_one(
        {"_id": release_oid},
        {"$inc": {"download_count": 1}},
    )
    return AppDownloadRecordResult(
        platform=platform,
        version=version,
        release_id=str(release_oid),
        download_url=_download_url(str(release_oid)),
        user_type=user_type,
    )
