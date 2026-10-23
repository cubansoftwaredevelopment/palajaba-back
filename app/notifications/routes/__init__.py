from fastapi import APIRouter

from app.notifications.routes.admin import router as admin_router
from app.notifications.routes.seller import router as seller_router

router = APIRouter()
router.include_router(admin_router)
router.include_router(seller_router)
