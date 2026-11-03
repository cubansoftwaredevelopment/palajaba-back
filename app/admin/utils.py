from app.config import settings


def is_admin_username(value: str) -> bool:
    return value.strip().casefold() == settings.admin_username.strip().casefold()
