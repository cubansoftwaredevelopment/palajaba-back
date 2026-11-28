from typing import Any

from fastapi import APIRouter, Depends, status

from app.auth.utils import require_gestor
from app.gestores.schemas import (
    GestorAllowedProductPublic,
    GestorLoginRequest,
    GestorLoginResponse,
    GestorPublic,
    GestorSelectedProductsUpdate,
    GestorSetupRequest,
)
from app.gestores import service as gestores_service

router = APIRouter(prefix="/api/gestores", tags=["gestores"])


@router.post("/login", response_model=GestorLoginResponse)
async def gestor_login(payload: GestorLoginRequest):
    return await gestores_service.login_gestor(
        store_name=payload.store_name,
        username=payload.username,
        password=payload.password,
    )


@router.post("/setup", response_model=GestorLoginResponse)
async def gestor_setup(payload: GestorSetupRequest):
    return await gestores_service.complete_gestor_setup(
        setup_token=payload.setup_token,
        password=payload.password,
        phone=payload.phone,
    )


@router.post("/me/sync")
async def sync_gestor_dates(payload: dict[str, Any], gestor_payload: dict = Depends(require_gestor)):
    from app.account_sync.gestor import compare_gestor

    return await compare_gestor(gestor_payload["gestor_id"], gestor_payload["seller_id"], payload)


@router.put("/me/sync/{section}")
async def push_gestor_section(section: str, payload: dict[str, Any], gestor_payload: dict = Depends(require_gestor)):
    from app.account_sync.gestor import apply_gestor_section

    return await apply_gestor_section(
        gestor_payload["gestor_id"],
        gestor_payload["seller_id"],
        section,
        payload.get("updated_at"),
        payload.get("data"),
    )


@router.get("/me", response_model=GestorPublic)
async def gestor_me(gestor_payload: dict = Depends(require_gestor)):
    return await gestores_service.get_gestor_public(
        gestor_payload["gestor_id"],
        gestor_payload["seller_id"],
    )


@router.get("/me/allowed-products", response_model=list[GestorAllowedProductPublic])
async def gestor_allowed_products(gestor_payload: dict = Depends(require_gestor)):
    return await gestores_service.list_allowed_products_for_gestor(
        gestor_payload["gestor_id"],
        gestor_payload["seller_id"],
    )


@router.put("/me/selected-products", response_model=GestorPublic)
async def update_gestor_selected_products(
    payload: GestorSelectedProductsUpdate,
    gestor_payload: dict = Depends(require_gestor),
):
    return await gestores_service.update_gestor_selected_products(
        gestor_payload["gestor_id"],
        gestor_payload["seller_id"],
        payload,
    )
