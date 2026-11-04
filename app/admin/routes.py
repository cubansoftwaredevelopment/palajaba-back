from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.admin.customers import list_admin_customers, set_customer_purchase_access
from app.admin.schemas import (
    AdminCustomerAccessUpdate,
    AdminCustomerPublic,
    AdminLoginRequest,
    AdminLoginResponse,
    PlatformPlanPricesPublic,
    PlatformRenewalContactPublic,
    PlatformSettingsPublic,
    PlatformSettingsUpdate,
)
from app.admin import service as admin_service
from app.auth import registrations as registration_service
from app.auth.schemas import RegistrationDeleteResult, RegistrationPublic
from app.auth.utils import create_admin_token, require_admin
from app.finance_admin.routes import router as finance_router
from app.notifications.routes.admin import router as notifications_router
from app.payments import disputes as dispute_service
from app.payments.schema import DisputeRulingRequest
from app.products.routes import admin_router as products_router
from app.schemas.banners import BannerAdminPublic, BannerUpdate
from app.schemas.discount_code import DiscountCodeCreate, DiscountCodeDeleteResult, DiscountCodePublic, DiscountCodeUpdate
from app.schemas.gestores import GestorPublic
from app.schemas.seller_feedback import AdminFeedbackDeleteResult, AdminFeedbackPublic, AdminFeedbackUnreadCount
from app.services import banners as banners_service
from app.services import discount_codes as discount_codes_service
from app.services import gestores as gestores_service
from app.services import seller_deletion as seller_deletion_service
from app.services import seller_feedback as seller_feedback_service
from app.statistics_admin.routes import router as statistics_router
from app.subscriptions.routes import router as subscriptions_router
from app.utils.dates import parse_subscription_end

router = APIRouter()
panel_router = APIRouter(prefix="/api/admin", tags=["admin"])
platform_router = APIRouter(prefix="/api/platform", tags=["platform"])


@panel_router.post("/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest):
    admin = await admin_service.authenticate_admin(payload.username.strip(), payload.password)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    return AdminLoginResponse(access_token=create_admin_token(username=admin["username"], admin_id=str(admin["_id"])))


@panel_router.get("/customers", response_model=list[AdminCustomerPublic])
async def list_customers(_: dict = Depends(require_admin)):
    return await list_admin_customers()


@panel_router.patch("/customers/{customer_id}/access", response_model=AdminCustomerPublic)
async def update_customer_access(customer_id: str, payload: AdminCustomerAccessUpdate, _: dict = Depends(require_admin)):
    return await set_customer_purchase_access(customer_id, purchase_revoked=payload.purchase_revoked)


@panel_router.get("/registrations", response_model=list[RegistrationPublic])
async def list_registrations(status_filter: Literal["pending", "approved", "rejected", "expired", "all"] = Query(default="pending", alias="status"), _: dict = Depends(require_admin)):
    return await registration_service.list_registrations(status_filter)


@panel_router.get("/registrations/{registration_id}", response_model=RegistrationPublic)
async def get_registration(registration_id: str, _: dict = Depends(require_admin)):
    return await registration_service.get_registration(registration_id)


@panel_router.delete("/registrations/{registration_id}", response_model=RegistrationDeleteResult)
async def delete_registration(registration_id: str, _: dict = Depends(require_admin)):
    result = await seller_deletion_service.delete_registration_document(registration_id)
    return RegistrationDeleteResult(**result)


@panel_router.post("/registrations/{registration_id}/approve", response_model=RegistrationPublic)
async def approve_registration(registration_id: str, payment_amount_cup: int = Query(..., ge=0, description="Monto real transferido en CUP (0 = acceso gratuito)"), subscription_ends_at: str | None = Query(default=None, description="Fecha de fin de suscripción (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"), _: dict = Depends(require_admin)):
    return await registration_service.approve_registration(registration_id, parse_subscription_end(subscription_ends_at), payment_amount_cup)


@panel_router.post("/registrations/{registration_id}/reject", response_model=RegistrationPublic)
async def reject_registration(registration_id: str, _: dict = Depends(require_admin)):
    return await registration_service.reject_registration(registration_id)


@panel_router.get("/registrations/{registration_id}/gestores", response_model=list[GestorPublic])
async def list_registration_gestores(registration_id: str, _: dict = Depends(require_admin)):
    return await gestores_service.list_seller_gestores_for_admin(registration_id)


@panel_router.patch("/registrations/{registration_id}/payment", response_model=RegistrationPublic)
async def update_payment(registration_id: str, payment_amount_cup: int = Query(..., ge=0, description="Monto transferido en CUP (0 = acceso gratuito)"), _: dict = Depends(require_admin)):
    return await registration_service.update_payment_amount(registration_id, payment_amount_cup)


@panel_router.get("/discount-codes", response_model=list[DiscountCodePublic])
async def list_discount_codes(_: dict = Depends(require_admin)):
    return await discount_codes_service.list_discount_codes()


@panel_router.post("/discount-codes", response_model=DiscountCodePublic, status_code=201)
async def create_discount_code(payload: DiscountCodeCreate, _: dict = Depends(require_admin)):
    return await discount_codes_service.create_discount_code(code=payload.code, percent_off=payload.percent_off, is_active=payload.is_active)


@panel_router.patch("/discount-codes/{discount_code_id}", response_model=DiscountCodePublic)
async def update_discount_code(discount_code_id: str, payload: DiscountCodeUpdate, _: dict = Depends(require_admin)):
    return await discount_codes_service.update_discount_code(discount_code_id, payload)


@panel_router.delete("/discount-codes/{discount_code_id}", response_model=DiscountCodeDeleteResult)
async def delete_discount_code(discount_code_id: str, _: dict = Depends(require_admin)):
    return await discount_codes_service.delete_discount_code(discount_code_id)


@panel_router.get("/feedback", response_model=list[AdminFeedbackPublic])
async def list_feedback(feedback_filter: Literal["all", "unread", "complaint", "suggestion"] = Query(default="all", alias="filter"), _: dict = Depends(require_admin)):
    return await seller_feedback_service.list_admin_feedback(feedback_filter=feedback_filter)


@panel_router.get("/feedback/unread-count", response_model=AdminFeedbackUnreadCount)
async def feedback_unread_count(_: dict = Depends(require_admin)):
    return await seller_feedback_service.get_admin_feedback_unread_count()


@panel_router.patch("/feedback/{feedback_id}/read", response_model=AdminFeedbackPublic)
async def mark_feedback_read(feedback_id: str, _: dict = Depends(require_admin)):
    return await seller_feedback_service.mark_admin_feedback_read(feedback_id)


@panel_router.delete("/feedback/{feedback_id}", response_model=AdminFeedbackDeleteResult)
async def delete_feedback(feedback_id: str, _: dict = Depends(require_admin)):
    return await seller_feedback_service.delete_admin_feedback(feedback_id)


@panel_router.get("/settings", response_model=PlatformSettingsPublic)
async def get_settings(_: dict = Depends(require_admin)):
    return await admin_service.get_platform_settings()


@panel_router.patch("/settings", response_model=PlatformSettingsPublic)
async def update_settings(payload: PlatformSettingsUpdate, _: dict = Depends(require_admin)):
    return await admin_service.update_platform_settings(payload)


@platform_router.get("/renewal-contact", response_model=PlatformRenewalContactPublic)
async def get_renewal_contact():
    stored = await admin_service.get_platform_settings()
    return PlatformRenewalContactPublic(renewal_contact_phone=stored.renewal_contact_phone)


@platform_router.get("/plan-prices", response_model=PlatformPlanPricesPublic)
async def get_plan_prices():
    return PlatformPlanPricesPublic(plan_prices=await admin_service.get_plan_prices())


@panel_router.get("/banners", response_model=list[BannerAdminPublic])
async def list_banners(_: dict = Depends(require_admin)):
    return await banners_service.list_admin_banners()


@panel_router.post("/banners", response_model=BannerAdminPublic, status_code=201)
async def create_banner(file: UploadFile = File(...), title: str | None = Form(default=None), link_url: str | None = Form(default=None), province_ids: list[str] = Form(default=[]), deactivate_at: str | None = Form(default=None), admin_payload: dict = Depends(require_admin)):
    return await banners_service.create_banner(file, admin_id=admin_payload.get("admin_id", "admin"), title=title, link_url=link_url, province_ids=province_ids, deactivate_at=deactivate_at)


@panel_router.patch("/banners/{banner_id}", response_model=BannerAdminPublic)
async def update_banner(banner_id: str, payload: BannerUpdate, _: dict = Depends(require_admin)):
    return await banners_service.update_banner(banner_id, payload)


@panel_router.post("/banners/{banner_id}/image", response_model=BannerAdminPublic)
async def replace_banner_image(banner_id: str, file: UploadFile = File(...), admin_payload: dict = Depends(require_admin)):
    return await banners_service.replace_banner_image(banner_id, file, admin_id=admin_payload.get("admin_id", "admin"))


@panel_router.delete("/banners/{banner_id}")
async def delete_banner(banner_id: str, _: dict = Depends(require_admin)):
    return await banners_service.delete_banner(banner_id)


@panel_router.get("/disputes/open-count")
async def disputes_open_count(_: dict = Depends(require_admin)):
    return {"count": await dispute_service.count_open_disputes()}


@panel_router.get("/disputes")
async def list_disputes(_: dict = Depends(require_admin)):
    return await dispute_service.list_disputes()


@panel_router.get("/disputes/{dispute_id}")
async def get_dispute(dispute_id: str, _: dict = Depends(require_admin)):
    return await dispute_service.get_dispute_detail(dispute_id)


@panel_router.get("/disputes/{dispute_id}/agreements/{kind}.pdf")
async def download_dispute_agreement(dispute_id: str, kind: Literal["terms", "delivery_policy"], _: dict = Depends(require_admin)):
    pdf_bytes, filename = await dispute_service.agreement_pdf(dispute_id, kind)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@panel_router.post("/disputes/{dispute_id}/ruling")
async def rule_dispute(dispute_id: str, payload: DisputeRulingRequest, _: dict = Depends(require_admin)):
    return await dispute_service.rule_dispute(
        dispute_id,
        winner=payload.winner,
        reason=payload.reason,
    )


router.include_router(panel_router)
router.include_router(platform_router)
router.include_router(products_router)
router.include_router(statistics_router)
router.include_router(finance_router)
router.include_router(notifications_router)
router.include_router(subscriptions_router)
