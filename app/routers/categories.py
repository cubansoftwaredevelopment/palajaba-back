from fastapi import APIRouter

from app.schemas.seller_profile import CategoryPublic
from app.services import categories as categories_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("/", response_model=list[CategoryPublic])
async def list_categories():
    return await categories_service.list_categories()
