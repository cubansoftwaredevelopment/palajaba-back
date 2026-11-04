from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.auth.utils import require_customer, require_seller
from app.orders.constants import InvoiceType
from app.orders.schemas import CreateOrderRequest, CreateSellerManualOrderRequest, OrderPublic, UpdateOrderRequest
from app.orders import service as orders_service

router = APIRouter()
seller_router = APIRouter(prefix="/api/auth", tags=["auth"])
buyer_router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@seller_router.get("/me/orders")
async def list_my_orders(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    seller_payload: dict = Depends(require_seller),
):
    return await orders_service.list_seller_orders(
        seller_payload["seller_id"], offset=offset, limit=limit
    )


@seller_router.post("/me/orders", response_model=OrderPublic, status_code=201)
async def create_my_manual_order(
    payload: CreateSellerManualOrderRequest,
    seller_payload: dict = Depends(require_seller),
):
    try:
        return await orders_service.create_seller_manual_order(
            seller_payload["seller_id"],
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@seller_router.patch("/me/orders/{order_id}", response_model=OrderPublic)
async def update_my_order(
    order_id: str,
    payload: UpdateOrderRequest,
    seller_payload: dict = Depends(require_seller),
):
    try:
        return await orders_service.update_seller_order(
            seller_payload["seller_id"],
            order_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@seller_router.delete("/me/orders/{order_id}", status_code=204)
async def delete_my_order(
    order_id: str,
    seller_payload: dict = Depends(require_seller),
):
    try:
        await orders_service.delete_seller_order(
            seller_payload["seller_id"],
            order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@seller_router.get("/me/orders/{order_id}/invoice.pdf")
async def download_my_order_invoice(
    order_id: str,
    type: InvoiceType = Query("store"),
    seller_payload: dict = Depends(require_seller),
):
    try:
        pdf_bytes, filename = await orders_service.generate_order_invoice_pdf(
            seller_payload["seller_id"],
            order_id,
            type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@seller_router.get("/me/orders/{order_id}/agreements/{kind}.pdf")
async def download_my_order_agreement(
    order_id: str,
    kind: Literal["terms", "delivery_policy"],
    seller_payload: dict = Depends(require_seller),
):
    try:
        pdf_bytes, filename = await orders_service.generate_order_agreement_pdf(
            seller_payload["seller_id"],
            order_id,
            kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@seller_router.get("/me/orders/{order_id}/evidence.pdf")
async def download_my_order_evidence(
    order_id: str,
    seller_payload: dict = Depends(require_seller),
):
    try:
        pdf_bytes, filename = await orders_service.generate_order_evidence_pdf(
            seller_payload["seller_id"],
            order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@buyer_router.post("/orders", response_model=OrderPublic, status_code=201)
async def create_marketplace_order(
    payload: CreateOrderRequest,
    customer_payload: dict = Depends(require_customer),
):
    try:
        return await orders_service.create_order(payload, customer_id=customer_payload["customer_id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


router.include_router(seller_router)
router.include_router(buyer_router)
