from fastapi import APIRouter

from app.live.routes.devices import router as devices_router
from app.live.routes.events import router as events_router

router = APIRouter(prefix="/api/live", tags=["live"])
router.include_router(devices_router)
router.include_router(events_router)
