from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.config import settings

client: AsyncIOMotorClient | None = None
db = None


async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(
        settings.mongodb_url,
        serverSelectionTimeoutMS=5000,
    )
    db = client[settings.database_name]

    from app.services.admins import ensure_admin_indexes, seed_default_admin
    from app.services.catalog import ensure_catalog_indexes
    from app.services.categories import ensure_category_seed
    from app.services.product_categories import ensure_product_category_seed
    from app.services.notifications import (
        ensure_notification_indexes,
        ensure_pending_order_notifications,
        ensure_subscription_expiring_notifications,
    )
    from app.services.orders import ensure_order_indexes
    from app.services.registrations import ensure_registration_indexes
    from app.services.media_storage import init_cloudinary
    from app.services.seller_stats import ensure_seller_stats_indexes
    from app.services.platform_settings import ensure_platform_settings_indexes
    from app.services.seller_profile import ensure_uploads_dir

    init_cloudinary()

    await ensure_registration_indexes()
    await ensure_order_indexes()
    await ensure_admin_indexes()
    await ensure_platform_settings_indexes()
    await ensure_notification_indexes()
    await ensure_pending_order_notifications()
    await ensure_catalog_indexes()
    await ensure_seller_stats_indexes()
    await ensure_category_seed()
    await ensure_product_category_seed()
    await seed_default_admin()
    await ensure_subscription_expiring_notifications()
    ensure_uploads_dir()


async def close_mongo_connection():
    global client
    if client:
        client.close()


def get_registrations_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["registrations"]


def get_admins_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["admins"]


def get_categories_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["categories"]


def get_notifications_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["seller_notifications"]


def get_catalog_categories_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["catalog_categories"]


def get_catalog_products_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["catalog_products"]


def get_product_categories_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["product_categories"]


def get_orders_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["seller_orders"]


def get_seller_profile_views_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["seller_profile_views"]


def get_platform_settings_collection() -> AsyncIOMotorCollection:
    if db is None:
        raise RuntimeError("MongoDB no está conectado")
    return db["platform_settings"]
