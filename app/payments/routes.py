import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.advertising.service import mark_advertising_paid
from app.payments.qvapay import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


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

    handled = await mark_advertising_paid(
        remote_id=str(payload.get("remote_id") or "") or None,
        transaction_uuid=str(payload.get("transaction_uuid") or payload.get("uuid") or "") or None,
        status_value=str(payload.get("status") or ""),
    )
    if not handled:
        logger.info("Webhook QvaPay ignorado: %s", payload.get("status"))
    return {"ok": True}
