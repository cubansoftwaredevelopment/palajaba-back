from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.app_releases import service as app_releases_service
from app.app_releases.schemas import (
    AppDownloadRecordResult,
    AppReleaseDeleteResult,
    AppReleaseMainsPublic,
    AppReleasePromptStatus,
    AppReleasePublic,
)
from app.auth.utils import require_admin, require_customer_or_seller
from app.live.devices import register_app_push_device
from app.live.schemas.device import AppPushDevicePublic, AppPushDeviceRegister

router = APIRouter()
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
marketplace_router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@admin_router.get("/app-releases", response_model=list[AppReleasePublic])
async def list_app_releases(
    platform: Literal["android", "ios"] | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    return await app_releases_service.list_admin_releases(platform=platform)


@admin_router.post("/app-releases", response_model=AppReleasePublic, status_code=201)
async def create_app_release(
    file: UploadFile = File(...),
    platform: Literal["android", "ios"] = Form(...),
    version: str = Form(...),
    admin_payload: dict = Depends(require_admin),
):
    return await app_releases_service.create_release(
        file,
        platform=platform,
        version=version,
        admin_id=admin_payload.get("admin_id", "admin"),
    )


@admin_router.post("/app-releases/{release_id}/set-main", response_model=AppReleasePublic)
async def set_main_app_release(release_id: str, _: dict = Depends(require_admin)):
    return await app_releases_service.set_main_release(release_id)


@admin_router.delete("/app-releases/{release_id}", response_model=AppReleaseDeleteResult)
async def delete_app_release(release_id: str, _: dict = Depends(require_admin)):
    return await app_releases_service.delete_release(release_id)


@marketplace_router.get("/app-releases/main", response_model=AppReleaseMainsPublic)
async def get_main_app_releases():
    return await app_releases_service.list_main_releases()


@marketplace_router.post(
    "/app-push-devices",
    response_model=AppPushDevicePublic,
    status_code=201,
)
async def register_native_app_push_device(payload: AppPushDeviceRegister):
    """Registra FCM de la app instalada sin exigir cuenta."""
    try:
        return await register_app_push_device(token=payload.token, platform=payload.platform)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@marketplace_router.get(
    "/app-releases/prompt-status",
    response_model=AppReleasePromptStatus,
)
async def get_app_release_prompt_status(
    account: dict = Depends(require_customer_or_seller),
):
    return await app_releases_service.get_prompt_status(
        user_type=account["user_type"],
        user_id=account["user_id"],
    )


@marketplace_router.get("/app-releases/{release_id}/file")
async def download_app_release_file(release_id: str):
    return await app_releases_service.stream_release_file(release_id)


@marketplace_router.post(
    "/app-releases/{release_id}/download",
    response_model=AppDownloadRecordResult,
)
async def record_app_release_download(
    release_id: str,
    account: dict = Depends(require_customer_or_seller),
):
    return await app_releases_service.record_authenticated_download(
        release_id,
        user_type=account["user_type"],
        user_id=account["user_id"],
    )


router.include_router(admin_router)
router.include_router(marketplace_router)
