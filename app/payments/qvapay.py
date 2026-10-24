from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import settings

QVAPAY_V2_BASE = "https://api.qvapay.com/v2"


@dataclass
class QvaPayInvoice:
    url: str
    transaction_uuid: str
    amount: float
    remote_id: str
    raw: dict[str, Any]


def qvapay_configured() -> bool:
    return bool(settings.qvapay_app_id.strip() and settings.qvapay_app_secret.strip())


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "app-id": settings.qvapay_app_id.strip(),
        "app-secret": settings.qvapay_app_secret.strip(),
    }


def webhook_url() -> str:
    return f"{settings.public_site_url.rstrip('/')}/api/payments/qvapay/webhook"


def verify_webhook_signature(*, body: bytes, signature: str | None) -> bool:
    secret = settings.qvapay_app_secret.strip().encode("utf-8")
    if not secret or not signature:
        return False
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    received = str(signature).strip()
    if len(expected) != len(received):
        return False
    return hmac.compare_digest(expected, received)


def _money(value: Any) -> float | None:
    try:
        amount = float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def _invoice_products(products: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in products or []:
        name = " ".join(str(raw.get("name") or "").split())
        price = _money(raw.get("price"))
        try:
            quantity = int(raw.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1
        if not name or price is None or quantity < 1:
            continue
        items.append({"name": name[:80], "price": price})
    return items


async def create_invoice(
    *,
    amount: float,
    description: str,
    remote_id: str,
    products: list[dict[str, Any]] | None = None,
) -> QvaPayInvoice:
    if not qvapay_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El cobro con QvaPay no está configurado.",
        )
    body: dict[str, Any] = {
        "amount": amount,
        "description": description[:255],
        "remote_id": remote_id,
        "webhook": webhook_url(),
    }
    invoice_products = _invoice_products(products)
    if invoice_products:
        body["products"] = invoice_products
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{QVAPAY_V2_BASE}/create_invoice",
                headers=_headers(),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos crear la factura de pago.",
        ) from exc

    payload: Any = {}
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}

    if response.status_code >= 400 or not isinstance(payload, dict):
        message = ""
        if isinstance(payload, dict):
            message = str(
                payload.get("message") or payload.get("error") or payload.get("detail") or ""
            ).strip()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=message or "QvaPay rechazó la factura.",
        )

    url = str(payload.get("url") or "").strip()
    transaction_uuid = str(payload.get("transaction_uuid") or payload.get("uuid") or "").strip()
    if not url or not transaction_uuid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="QvaPay no devolvió la URL de pago.",
        )
    try:
        invoice_amount = float(payload.get("amount", amount))
    except (TypeError, ValueError):
        invoice_amount = float(amount)
    return QvaPayInvoice(
        url=url,
        transaction_uuid=transaction_uuid,
        amount=invoice_amount,
        remote_id=str(payload.get("remote_id") or remote_id),
        raw=payload,
    )
