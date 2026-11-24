from fastapi import APIRouter

from app.categories.schemas import CategoryPublic
from app.categories import service as categories_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("/", response_model=list[CategoryPublic])
async def list_categories():
    return await categories_service.list_categories()
