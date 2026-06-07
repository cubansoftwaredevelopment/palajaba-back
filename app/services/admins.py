from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.database import get_admins_collection
from app.security import hash_password, verify_password


async def ensure_admin_indexes() -> None:
    collection = get_admins_collection()
    await collection.create_index("username", unique=True)


async def seed_default_admin() -> bool:
    """Crea el admin por defecto si no existe. Devuelve True si se insertó."""
    collection = get_admins_collection()
    existing = await collection.find_one({"username": settings.admin_username})
    if existing:
        return False

    now = datetime.now(UTC)
    await collection.insert_one(
        {
            "username": settings.admin_username,
            "password_hash": hash_password(settings.admin_password),
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    return True


async def authenticate_admin(username: str, password: str) -> dict[str, Any] | None:
    collection = get_admins_collection()
    admin = await collection.find_one({"username": username, "is_active": True})
    if admin is None:
        return None
    if not verify_password(password, admin["password_hash"]):
        return None
    return admin
