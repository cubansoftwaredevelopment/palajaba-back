from fastapi import APIRouter

from app.schemas.seller_profile import CategoryPublic
from app.services import product_categories as product_categories_service

router = APIRouter(prefix="/api/product-categories", tags=["product-categories"])


@router.get("/", response_model=list[CategoryPublic])
async def list_product_categories():
    return await product_categories_service.list_product_categories()
