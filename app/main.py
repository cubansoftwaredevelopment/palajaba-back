from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo
from app.live.routes import router as live_router
from app.notifications.routes import router as notifications_router
from app.auth.routes import router as account_router
from app.customer_accounts.routes import router as customer_accounts_router
from app.orders.routes import router as orders_router
from app.products.routes import router as products_router
from app.admin.routes import router as admin_router
from app.seller_statistics.routes import router as seller_statistics_router
from app.statistics_admin.routes import public_router as statistics_public_router
from app.advertising.routes import router as advertising_router
from app.payments.routes import account_router as payment_workflow_router
from app.payments.routes import router as payments_router
from app.payments.evidence_clock import start_evidence_clock_task, stop_evidence_clock_task
from app.payments.service import start_expiry_task, stop_expiry_task
from app.routers import auth, categories, marketplace, platform, product_categories, seo, gestores
from app.notifications.service import (
    start_subscription_reminder_task,
    stop_subscription_reminder_task,
)
from app.services.exchange_rates import (
    start_exchange_rates_refresh_task,
    stop_exchange_rates_refresh_task,
)

UPLOADS_ROOT = Path(__file__).resolve().parent.parent / "uploads"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    start_exchange_rates_refresh_task()
    start_subscription_reminder_task()
    start_evidence_clock_task()
    start_expiry_task()
    yield
    await stop_subscription_reminder_task()
    await stop_evidence_clock_task()
    await stop_expiry_task()
    await stop_exchange_rates_refresh_task()
    await close_mongo_connection()


app = FastAPI(title="Pa' La Jaba API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account_router)
app.include_router(customer_accounts_router)
app.include_router(auth.router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(gestores.router)
app.include_router(categories.router)
app.include_router(product_categories.router)
app.include_router(marketplace.router)
app.include_router(platform.router)
app.include_router(advertising_router)
app.include_router(payments_router)
app.include_router(payment_workflow_router)
app.include_router(seo.router)
app.include_router(admin_router)
app.include_router(statistics_public_router)
app.include_router(seller_statistics_router)
app.include_router(notifications_router)
app.include_router(live_router)

UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_ROOT), name="uploads")


# 1×1 PNG: rutas legacy de banners locales; evita 404 + reintentos infinitos del navegador (ceRetry).
_LEGACY_BANNER_PIXEL = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f"
    b"\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@app.get("/api/catalog/banners/{banner_id}/file")
async def legacy_catalog_banner_file(banner_id: str):
    return Response(
        content=_LEGACY_BANNER_PIXEL,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Legacy-Banner": banner_id,
        },
    )


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "mongodb": "atlas" if settings.mongodb_url.startswith("mongodb+srv://") else "local",
        "cloudinary": settings.cloudinary_enabled,
        "cors_origins_count": len(settings.cors_origins_list),
    }
