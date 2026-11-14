from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.app_releases.schemas import (
    AppDownloadRecordResult,
    AppReleaseDeleteResult,
    AppReleaseMainsPublic,
    AppReleasePublic,
)
from app.database import get_app_download_records_collection, get_app_releases_collection
from app.utils.datetime import to_utc_naive, utc_now

AppPlatform = Literal["android", "ios"]

MAX_RELEASES_PER_PLATFORM = 5
MAX_APP_BYTES = 200 * 1024 * 1024
UPLOADS_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "app-releases"

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
    )


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


def _store_app_file(platform: AppPlatform, content: bytes, original_filename: str) -> tuple[str, Path]:
    folder = UPLOADS_ROOT / platform
    folder.mkdir(parents=True, exist_ok=True)
    ext = _PLATFORM_EXTENSIONS[platform]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = folder / stored_name
    path.write_bytes(content)
    relative = f"app-releases/{platform}/{stored_name}"
    return relative, path


def _absolute_path(file_path: str) -> Path:
    relative = str(file_path or "").replace("\\", "/").lstrip("/")
    if relative.startswith("uploads/"):
        relative = relative[len("uploads/") :]
    path = (Path(__file__).resolve().parents[2] / "uploads" / relative).resolve()
    root = (Path(__file__).resolve().parents[2] / "uploads").resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        )
    return path


async def _delete_file(file_path: str | None) -> None:
    if not file_path:
        return
    path = _absolute_path(str(file_path))
    try:
        if path.is_file():
            path.unlink()
    except OSError:
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
        await _delete_file(victim.get("file_path"))
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
    relative_path, _ = _store_app_file(normalized_platform, content, original_filename)
    now = to_utc_naive(utc_now())
    collection = get_app_releases_collection()
    existing_main = await collection.find_one(
        {"platform": normalized_platform, "is_main": True},
        {"_id": 1},
    )
    doc = {
        "platform": normalized_platform,
        "version": normalized_version,
        "file_path": relative_path,
        "file_url": f"/uploads/{relative_path}",
        "original_filename": original_filename,
        "content_type": content_type,
        "size_bytes": len(content),
        "is_main": existing_main is None,
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
    await collection.update_many(
        {"platform": platform, "is_main": True},
        {"$set": {"is_main": False}},
    )
    await collection.update_one({"_id": doc["_id"]}, {"$set": {"is_main": True}})
    updated = await collection.find_one({"_id": doc["_id"]})
    assert updated is not None
    return _document_to_public(updated)


async def delete_release(release_id: str) -> AppReleaseDeleteResult:
    doc = await _get_release_or_404(release_id)
    if doc.get("is_main"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar el build principal. Marca otro como main primero.",
        )
    await _delete_file(doc.get("file_path"))
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


async def stream_release_file(release_id: str) -> FileResponse:
    doc = await _get_release_or_404(release_id)
    path = _absolute_path(str(doc.get("file_path") or ""))
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        )
    filename = str(doc.get("original_filename") or path.name)
    media_type = str(doc.get("content_type") or "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment",
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
    await get_app_download_records_collection().update_one(
        {
            "user_type": user_type,
            "user_id": str(user_id),
            "platform": platform,
        },
        {
            "$set": {
                "version": version,
                "release_id": str(doc["_id"]),
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )
    return AppDownloadRecordResult(
        platform=platform,
        version=version,
        release_id=str(doc["_id"]),
        download_url=_download_url(str(doc["_id"])),
        user_type=user_type,
    )
