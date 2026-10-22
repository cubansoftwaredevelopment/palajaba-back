from fastapi import APIRouter

from app.register.routes.otp import router as otp_router

router = APIRouter(prefix="/api/register", tags=["register"])
router.include_router(otp_router)
