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
QVAPAY_API_BASE = "https://api.qvapay.com"


@dataclass
class QvaPayInvoice:
    url: str
    transaction_uuid: str
    amount: float
    remote_id: str
    raw: dict[str, Any]


def qvapay_configured() -> bool:
    return bool(settings.qvapay_app_id.strip() and settings.qvapay_app_secret.strip())


def qvapay_escrow_configured() -> bool:
    return qvapay_configured()


async def verify_qvapay_username(username: str) -> str:
    """Verifica el username en QvaPay, salvo en entorno de desarrollo."""
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Escribe tu usuario QvaPay.")
    if settings.app_env == "development":
        return normalized

    token = settings.qvapay_user_bearer_token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La verificación de cuentas QvaPay no está configurada.",
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{QVAPAY_API_BASE}/user/search",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"query": normalized},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="No pudimos verificar el usuario QvaPay.") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail="QvaPay no pudo verificar el usuario ahora.")
    try:
        results = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="QvaPay devolvió una respuesta inválida.") from exc
    if not isinstance(results, list) or not any(
        isinstance(item, dict) and str(item.get("username") or "").strip().lower() == normalized
        for item in results
    ):
        raise HTTPException(status_code=400, detail="No encontramos ese usuario en QvaPay.")
    return normalized


async def transfer_to_user(*, amount: float, username: str, description: str, idempotency_key: str) -> str:
    if not qvapay_escrow_configured():
        raise HTTPException(status_code=503, detail="Las transferencias QvaPay no están configuradas.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{QVAPAY_API_BASE}/transaction/transfer",
                headers=_headers(),
                json={
                    "amount": amount,
                    "to": username,
                    "description": description[:255],
                    "idempotency_key": idempotency_key,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="No pudimos liberar el pago por QvaPay.") from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    if response.status_code >= 400 or not isinstance(payload, dict) or payload.get("success") is False:
        message = str(payload.get("message") or payload.get("error") or "").strip() if isinstance(payload, dict) else ""
        raise HTTPException(status_code=503, detail=message or "QvaPay rechazó la transferencia.")
    transaction = str(payload.get("transaction") or "").strip()
    if not transaction:
        raise HTTPException(status_code=503, detail="QvaPay no confirmó la transferencia.")
    return transaction


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "app-id": settings.qvapay_app_id.strip(),
        "app-secret": settings.qvapay_app_secret.strip(),
    }


def webhook_url() -> str:
    return f"{settings.public_api_url.rstrip('/')}/api/payments/qvapay/webhook"


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


def _cents(amount: float) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _format_cents(cents: int) -> str:
    return f"{(Decimal(cents) / Decimal(100)).quantize(Decimal('0.01')):.2f}"


def _split_cents(total: int, weights: list[int]) -> list[int]:
    count = len(weights)
    if count == 0:
        return []
    weight_sum = sum(weights)
    if total <= 0 or weight_sum <= 0:
        return [0] * count
    raw = [total * weight for weight in weights]
    shares = [value // weight_sum for value in raw]
    leftover = total - sum(shares)
    order = sorted(
        range(count),
        key=lambda index: (raw[index] % weight_sum, weights[index]),
        reverse=True,
    )
    for index in order[:leftover]:
        shares[index] += 1
    return shares


def _is_delivery_name(name: str) -> bool:
    return name.strip().lower() in {"domicilio", "envio", "envío"}


def _absorb_fee(articles: list[dict[str, Any]], deliveries: list[dict[str, Any]], fee_cents: int) -> None:
    if fee_cents <= 0 or not (articles or deliveries):
        return
    article_weight = sum(int(line["cents"]) for line in articles)
    delivery_weight = sum(int(line["cents"]) for line in deliveries)
    if article_weight <= 0 and delivery_weight <= 0:
        return
    if article_weight <= 0:
        article_fee, delivery_fee = 0, fee_cents
    elif delivery_weight <= 0:
        article_fee, delivery_fee = fee_cents, 0
    else:
        article_fee, delivery_fee = _split_cents(fee_cents, [article_weight, delivery_weight])
    if article_fee and articles:
        for line, share in zip(articles, _split_cents(article_fee, [int(line["cents"]) for line in articles])):
            line["cents"] = int(line["cents"]) + share
    if delivery_fee and deliveries:
        for line, share in zip(deliveries, _split_cents(delivery_fee, [int(line["cents"]) for line in deliveries])):
            line["cents"] = int(line["cents"]) + share


def _invoice_products(
    products: list[dict[str, Any]] | None, *, invoice_amount: float
) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    fee_cents = 0
    for raw in products or []:
        name = " ".join(
            "".join(char if char.isprintable() else " " for char in str(raw.get("name") or "")).split()
        )
        price = _money(raw.get("price"))
        try:
            quantity = int(raw.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1
        if not name or price is None or quantity < 1:
            continue
        if raw.get("is_fee") is True or name.strip().lower() == "fee":
            fee_cents += _cents(price)
            continue
        line = {"name": name, "quantity": quantity, "cents": _cents(price)}
        if _is_delivery_name(name):
            deliveries.append(line)
        else:
            articles.append(line)
    _absorb_fee(articles, deliveries, fee_cents)
    details = [
        f"{line['name']} x{line['quantity']}: {_format_cents(int(line['cents']))}"
        for line in (*articles, *deliveries)
    ]
    total = _money(invoice_amount)
    if not details or total is None:
        return []
    return [{"name": ", ".join(details), "price": total}]


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
    
    invoice_products = _invoice_products(products, invoice_amount=amount)
    if invoice_products:
        body["products"] = invoice_products

    print("QvaPay request body:", body)
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
