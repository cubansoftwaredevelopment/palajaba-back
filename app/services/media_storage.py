import io
import re
import uuid
from pathlib import Path
from typing import Literal

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile, status

from app.config import settings

MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

LOCAL_UPLOADS_ROOT = Path(__file__).resolve().parents[2] / "uploads"
ImageScope = Literal["products", "profiles"]

_EXTENSION_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def init_cloudinary() -> None:
    if not settings.cloudinary_enabled:
        return
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def _extension_for(content_type: str) -> str:
    return _EXTENSION_BY_TYPE.get(content_type, ".jpg")


def _public_id_from_url(url: str) -> str | None:
    match = re.search(r"/upload/(?:v\d+/)?(.+?)(?:\.[a-zA-Z0-9]+)?$", url)
    if not match:
        return None
    return match.group(1)


async def read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen debe ser JPG, PNG o WebP.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen está vacía.",
        )
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen no puede superar 4 MB.",
        )

    return content, file.content_type


async def store_image(
    content: bytes,
    content_type: str,
    *,
    scope: ImageScope,
    owner_id: str,
) -> str:
    if settings.cloudinary_enabled:
        return _upload_to_cloudinary(content, scope=scope, owner_id=owner_id)

    return _save_local_image(content, content_type, scope=scope, owner_id=owner_id)


def remove_image(url: str | None) -> None:
    if not url:
        return

    if url.startswith("http://") or url.startswith("https://"):
        if "res.cloudinary.com" not in url or not settings.cloudinary_enabled:
            return
        public_id = _public_id_from_url(url)
        if not public_id:
            return
        try:
            cloudinary.uploader.destroy(public_id, resource_type="image")
        except Exception:
            return
        return

    if url.startswith("/uploads/"):
        relative = url.removeprefix("/uploads/")
        filepath = LOCAL_UPLOADS_ROOT / relative
        filepath.unlink(missing_ok=True)


def _upload_to_cloudinary(content: bytes, *, scope: ImageScope, owner_id: str) -> str:
    folder = f"pala-jaba/{scope}"
    public_id = f"{owner_id}-{uuid.uuid4().hex[:12]}"
    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(content),
            folder=folder,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo subir la imagen a Cloudinary.",
        ) from exc

    secure_url = result.get("secure_url")
    if not secure_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloudinary no devolvió una URL válida.",
        )
    return secure_url


def _save_local_image(
    content: bytes,
    content_type: str,
    *,
    scope: ImageScope,
    owner_id: str,
) -> str:
    dest_dir = LOCAL_UPLOADS_ROOT / scope
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{owner_id}-{uuid.uuid4().hex[:8]}{_extension_for(content_type)}"
    filepath = dest_dir / filename
    filepath.write_bytes(content)
    return f"/uploads/{scope}/{filename}"
