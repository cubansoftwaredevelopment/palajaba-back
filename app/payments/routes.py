import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from app.advertising.service import mark_advertising_paid
from app.payments.qvapay import verify_webhook_signature
from app.payments import refunds as refund_service
from app.payments import service
from app.payments import subscription_service
from app.payments import disputes as dispute_service
from app.payments.schema import (
    CustomerDeviceDelete,
    CustomerDeviceRequest,
    DisputeOpenRequest,
    DisputeRulingRequest,
    EvidenceSubmitRequest,
    QvaPayAccountRequest,
    StoreRefundRequest,
    SellerAcceptPaymentRequest,
    SubscriptionPlanCheckoutRequest,
)
from app.auth.utils import require_active_seller, require_customer, require_seller
from app.live.devices import delete_customer_device, register_customer_device

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])
account_router = APIRouter(tags=["payment workflows"])


@router.post("/qvapay/webhook")
async def qvapay_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("x-qvapay-signature")
    if not verify_webhook_signature(body=body, signature=signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma de QvaPay inválida.",
        )
    try:
        payload: Any = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El webhook de QvaPay no es JSON válido.",
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El webhook de QvaPay no es JSON válido.",
        )

    remote_id = str(payload.get("remote_id") or "") or None
    transaction_uuid = str(payload.get("transaction_uuid") or payload.get("uuid") or "") or None
    status_value = str(payload.get("status") or "")
    handled = await service.mark_qvapay_invoice_paid(
        remote_id=remote_id,
        transaction_uuid=transaction_uuid,
        status_value=status_value,
    )
    if not handled:
        handled = await subscription_service.mark_subscription_plan_invoice_paid(
            remote_id=remote_id,
            transaction_uuid=transaction_uuid,
            status_value=status_value,
        )
    if not handled:
        handled = await mark_advertising_paid(
            remote_id=remote_id,
            transaction_uuid=transaction_uuid,
            status_value=status_value,
        )
    if not handled:
        logger.info("Webhook QvaPay ignorado: %s", payload.get("status"))
    return {"ok": True}


@account_router.post("/api/auth/me/subscriptions/qvapay")
async def create_subscription_plan_qvapay_checkout(
    payload: SubscriptionPlanCheckoutRequest,
    seller: dict = Depends(require_seller),
):
    return await subscription_service.create_subscription_plan_checkout(
        seller_id=seller["seller_id"],
        plan_tier=payload.plan_tier,
        billing_period=payload.billing_period,
    )


@account_router.post("/api/register/qvapay")
async def create_initial_subscription_qvapay_checkout(payload: SubscriptionPlanCheckoutRequest):
    return await subscription_service.create_initial_subscription_checkout(
        plan_tier=payload.plan_tier,
        billing_period=payload.billing_period,
    )


@account_router.get("/api/register/qvapay/{purchase_id}")
async def get_initial_subscription_qvapay_checkout(purchase_id: str):
    return await subscription_service.get_public_initial_subscription_checkout(purchase_id=purchase_id)


@account_router.get("/api/auth/me/subscriptions/qvapay/{purchase_id}")
async def get_subscription_plan_qvapay_checkout(
    purchase_id: str,
    seller: dict = Depends(require_seller),
):
    return await subscription_service.get_subscription_plan_checkout(
        seller_id=seller["seller_id"], purchase_id=purchase_id
    )


@account_router.get("/api/auth/me/payment-methods/qvapay")
async def get_seller_qvapay_account(seller: dict = Depends(require_seller)):
    return await service.get_qvapay_account(seller["seller_id"])


@account_router.put("/api/auth/me/payment-methods/qvapay")
async def put_seller_qvapay_account(payload: QvaPayAccountRequest, seller: dict = Depends(require_active_seller)):
    return await service.save_qvapay_account(
        seller["seller_id"],
        payload.username,
        skip_verification_on_service_error=payload.skip_verification,
    )


@account_router.delete("/api/auth/me/payment-methods/qvapay", status_code=204)
async def delete_seller_qvapay_account(seller: dict = Depends(require_active_seller)):
    await service.delete_qvapay_account(seller["seller_id"])


@account_router.post("/api/auth/me/payment-methods/qvapay/dismiss", status_code=204)
async def dismiss_seller_qvapay_prompt(seller: dict = Depends(require_active_seller)):
    await service.dismiss_qvapay_prompt(seller["seller_id"])


@account_router.get("/api/customers/me/payment-methods/qvapay")
async def get_customer_qvapay_account(customer: dict = Depends(require_customer)):
    return await service.get_customer_qvapay_account(customer["customer_id"])


@account_router.put("/api/customers/me/payment-methods/qvapay")
async def put_customer_qvapay_account(payload: QvaPayAccountRequest, customer: dict = Depends(require_customer)):
    return await service.save_customer_qvapay_account(
        customer["customer_id"],
        payload.username,
        skip_verification_on_service_error=payload.skip_verification,
    )


@account_router.delete("/api/customers/me/payment-methods/qvapay", status_code=204)
async def delete_customer_qvapay_account(customer: dict = Depends(require_customer)):
    await service.delete_customer_qvapay_account(customer["customer_id"])


@account_router.post("/api/customers/me/payment-methods/qvapay/dismiss", status_code=204)
async def dismiss_customer_qvapay_prompt(customer: dict = Depends(require_customer)):
    await service.dismiss_customer_qvapay_prompt(customer["customer_id"])


@account_router.post("/api/customers/me/orders/{order_id}/disputes/images")
async def upload_customer_dispute_image(order_id: str, photo: UploadFile = File(...), customer: dict = Depends(require_customer)):
    return await dispute_service.upload_dispute_image(order_id, "buyer", customer["customer_id"], photo)


@account_router.post("/api/customers/me/orders/{order_id}/disputes")
async def open_customer_order_dispute(order_id: str, payload: DisputeOpenRequest, customer: dict = Depends(require_customer)):
    return await dispute_service.open_dispute(order_id, "buyer", customer["customer_id"], text=payload.text, images=payload.images)


@account_router.post("/api/auth/me/orders/{order_id}/disputes/images")
async def upload_seller_dispute_image(order_id: str, photo: UploadFile = File(...), seller: dict = Depends(require_active_seller)):
    return await dispute_service.upload_dispute_image(order_id, "seller", seller["seller_id"], photo)


@account_router.post("/api/auth/me/orders/{order_id}/disputes")
async def open_seller_order_dispute(order_id: str, payload: DisputeOpenRequest, seller: dict = Depends(require_active_seller)):
    return await dispute_service.open_dispute(order_id, "seller", seller["seller_id"], text=payload.text, images=payload.images)


@account_router.post("/api/auth/me/orders/{order_id}/qvapay/refund/images")
async def upload_seller_refund_image(order_id: str, photo: UploadFile = File(...), seller: dict = Depends(require_active_seller)):
    return await refund_service.upload_refund_image(seller["seller_id"], order_id, photo)


@account_router.post("/api/auth/me/orders/{order_id}/qvapay/refund")
async def refund_seller_qvapay_order(order_id: str, payload: StoreRefundRequest, seller: dict = Depends(require_active_seller)):
    return await refund_service.refund_order_for_store(
        seller["seller_id"],
        order_id,
        quantities={item.product_id: item.quantity for item in payload.items},
        refund_delivery=payload.refund_delivery,
        text=payload.text,
        images=payload.images,
    )


@account_router.post("/api/auth/me/orders/{order_id}/qvapay/accept")
async def accept_seller_qvapay_order(order_id: str, payload: SellerAcceptPaymentRequest, seller: dict = Depends(require_active_seller)):
    try:
        return await service.accept_payment_request(
            seller["seller_id"], order_id,
            delivery_price=payload.delivery_price,
            delivery_currency=payload.delivery_currency,
        )
    except HTTPException:
        raise


@account_router.post("/api/auth/me/orders/{order_id}/qvapay/reject", status_code=204)
async def reject_seller_qvapay_order(order_id: str, seller: dict = Depends(require_active_seller)):
    await service.reject_payment_request(seller["seller_id"], order_id)


@account_router.post("/api/auth/me/orders/{order_id}/evidence/images")
async def upload_seller_order_evidence_image(order_id: str, photo: UploadFile = File(...), seller: dict = Depends(require_active_seller)):
    return await service.upload_evidence_image(seller["seller_id"], order_id, photo)


@account_router.post("/api/auth/me/orders/{order_id}/evidence")
async def submit_seller_order_evidence(order_id: str, payload: EvidenceSubmitRequest, seller: dict = Depends(require_active_seller)):
    return await service.submit_evidence(seller["seller_id"], order_id, payload.content)


@account_router.post("/api/customers/me/orders/{order_id}/qvapay/evidence/accept")
async def accept_customer_order_evidence(order_id: str, customer: dict = Depends(require_customer)):
    return await service.customer_evidence_decision(customer["customer_id"], order_id, accept=True)


@account_router.post("/api/customers/me/orders/{order_id}/qvapay/evidence/reject")
async def reject_customer_order_evidence(order_id: str, customer: dict = Depends(require_customer)):
    return await service.customer_evidence_decision(customer["customer_id"], order_id, accept=False)


@account_router.get("/api/customers/me/notifications")
async def list_customer_order_notifications(customer: dict = Depends(require_customer)):
    return await service.list_customer_notifications(customer["customer_id"])


@account_router.patch("/api/customers/me/notifications/{notification_id}/read")
async def read_customer_order_notification(notification_id: str, customer: dict = Depends(require_customer)):
    return await service.mark_customer_notification_read(customer["customer_id"], notification_id)


@account_router.post("/api/customers/me/notifications/read-all")
async def read_all_customer_order_notifications(customer: dict = Depends(require_customer)):
    return await service.mark_all_customer_notifications_read(customer["customer_id"])


@account_router.post("/api/live/customer-devices", status_code=201)
async def register_customer_push_device(payload: CustomerDeviceRequest, customer: dict = Depends(require_customer)):
    await register_customer_device(customer["customer_id"], payload)
    return {"registered": True}


@account_router.delete("/api/live/customer-devices", status_code=204)
async def unregister_customer_push_device(payload: CustomerDeviceDelete, customer: dict = Depends(require_customer)):
    await delete_customer_device(customer["customer_id"], payload.token)
