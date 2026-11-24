from __future__ import annotations

import math
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, status

from app.catalogs.media_storage import ALLOWED_IMAGE_TYPES, LOCAL_UPLOADS_ROOT

_USERNAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
VEHICLE_TYPES = ("bicicleta", "moto", "triciclo", "auto", "camioneta", "camion")
PAY_CURRENCIES = ("CUP", "USD", "EUR", "MLC", "QUSD")
ACTIVE_ASSIGNMENT = ("assigned", "in_route")


def normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) < 2 or len(normalized) > 32 or not _USERNAME_PATTERN.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El alias debe tener entre 2 y 32 caracteres: letras, números, guiones y guiones bajos.",
        )
    return normalized


def save_image(content: bytes, content_type: str, owner_id: str) -> str:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="La imagen debe ser JPG, PNG o WebP.")
    if not content:
        raise HTTPException(status_code=400, detail="La imagen está vacía.")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="La foto pesa demasiado.")
    extension = { "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp" }[content_type]
    dest = LOCAL_UPLOADS_ROOT / "mensajeros"
    dest.mkdir(parents=True, exist_ok=True)
    filename = f"{owner_id}-{uuid.uuid4().hex[:8]}{extension}"
    path = Path(dest / filename)
    path.write_bytes(content)
    return f"/uploads/mensajeros/{filename}"


def haversine_km(points: list[dict]) -> float:
    total = 0.0
    previous = None
    for point in points:
        current = (float(point["lat"]), float(point["lng"]))
        if previous is not None:
            total += _distance_km(previous, current)
        previous = current
    return round(total, 2)


def distance_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    return _distance_km(origin, destination)


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))
