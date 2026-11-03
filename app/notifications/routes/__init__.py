from fastapi import APIRouter

from app.notifications.routes.seller import router as seller_router

router = APIRouter()
router.include_router(seller_router)
