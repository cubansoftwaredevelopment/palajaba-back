from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo
from app.routers import admin, auth, categories, marketplace, product_categories, register

UPLOADS_ROOT = Path(__file__).resolve().parent.parent / "uploads"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(title="Pa' La Jaba API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(register.router)
app.include_router(auth.router)
app.include_router(categories.router)
app.include_router(product_categories.router)
app.include_router(marketplace.router)
app.include_router(admin.router)

UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_ROOT), name="uploads")


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "mongodb": "atlas" if settings.mongodb_url.startswith("mongodb+srv://") else "local",
        "cloudinary": settings.cloudinary_enabled,
    }
