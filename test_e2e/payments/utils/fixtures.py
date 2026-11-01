"""Datos, firma de webhook y limpieza del E2E de escrow QvaPay."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

from bson import ObjectId

from app.database import (
    get_customers_collection,
    get_orders_collection,
    get_registrations_collection,
    get_subscription_qvapay_purchases_collection,
)
from app.utils.datetime import to_utc_naive, utc_now

MARKER = "qvapay_escrow_e2e_v1"
SECRET = "qvapay-escrow-e2e-secret"
PLAN_MARKER = "qvapay_plan_e2e_v1"


async def seed_order(seller_id: str, *, deadline=None) -> dict[str, str]:
    seller_oid, customer_oid, order_oid = ObjectId(seller_id), ObjectId(), ObjectId()
    now = to_utc_naive(utc_now())
    await get_registrations_collection().update_one(
        {"_id": seller_oid},
        {"$set": {
            "qvapay_username": f"seller{seller_id[-6:]}",
            "qvapay_verified_at": now,
            "qvapay_e2e_marker": MARKER,
        }},
    )
    await get_customers_collection().insert_one(
        {
            "_id": customer_oid,
            "full_name": "Cliente QvaPay E2E",
            "email": f"customer-{customer_oid}@qvapay-e2e.test",
            "phone": f"{(int(str(customer_oid), 16) % 90000000) + 10000000:08d}",
            "identity_card": f"E2E{str(customer_oid)[-8:]}",
            MARKER: True,
        }
    )
    qvapay = {
        "request_status": "pending_seller",
        "payment_status": "not_invoiced",
        "release_status": "held",
        "evidence": None,
    }
    order = {
        "_id": order_oid,
        "seller_id": str(seller_oid),
        "store_id": str(seller_oid),
        "store_name": "Tienda QvaPay E2E",
        "status": "pending_confirmation",
        "items": [{"product_id": "producto-e2e", "name": "Arroz", "quantity": 1,
                    "unit_price": 400, "currency": "CUP", "line_total": 400}],
        "subtotals": [{"currency": "CUP", "amount": 400}],
        "delivery_requested": True,
        "delivery": {"recipient_name": "Cliente QvaPay E2E", "address": "Calle E2E",
                     "phone_primary": "51234567", "phone_secondary": None, "notes": None,
                     "latitude": None, "longitude": None},
        "delivery_price": None,
        "delivery_currency": None,
        "payment_currency": "CUP",
        "buyer_id": str(customer_oid),
        "buyer_name": "Cliente QvaPay E2E",
        "buyer_email": f"customer-{customer_oid}@qvapay-e2e.test",
        "buyer_phone": "",
        "payment_method": "qvapay",
        "qvapay": qvapay,
        "created_at": now,
        "updated_at": now,
        MARKER: True,
    }
    if deadline:
        order["qvapay"].update(
            {
                "request_status": "accepted",
                "payment_status": "paid",
                "release_status": "held",
                "products_amount_usd": 1.0,
                "delivery_amount_usd": 1.0,
                "fee_usd": 1.41,
                "invoice_amount_usd": 3.41,
                "evidence": {
                    "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Entregado"}]}]},
                    "status": "pending",
                    "sent_at": now - timedelta(hours=48),
                    "deadline": deadline,
                },
            }
        )
    await get_orders_collection().insert_one(order)
    return {"order_id": str(order_oid), "customer_id": str(customer_oid), "seller_id": str(seller_oid)}


async def cleanup() -> None:
    await get_orders_collection().delete_many({MARKER: True})
    await get_customers_collection().delete_many({MARKER: True})
    await get_registrations_collection().delete_many({"qvapay_e2e_marker": MARKER})


async def cleanup_plan_purchases() -> None:
    registrations = get_registrations_collection()
    purchases = get_subscription_qvapay_purchases_collection()
    test_transaction_ids = ["plan-tx-e2e", "signup-tx-e2e"]
    seller_ids = [str(doc["_id"]) async for doc in registrations.find({PLAN_MARKER: True}, {"_id": 1})]
    async for doc in purchases.find({PLAN_MARKER: True, "seller_id": {"$ne": None}}, {"seller_id": 1}):
        seller_ids.append(str(doc["seller_id"]))
    async for doc in purchases.find({"transaction_uuid": {"$in": test_transaction_ids}, "seller_id": {"$ne": None}}, {"seller_id": 1}):
        seller_ids.append(str(doc["seller_id"]))
    if seller_ids:
        await purchases.delete_many({"seller_id": {"$in": seller_ids}})
    await purchases.delete_many({"transaction_uuid": {"$in": test_transaction_ids}})
    await registrations.delete_many({PLAN_MARKER: True})
    await purchases.delete_many({PLAN_MARKER: True})


async def seed_inactive_plan_seller() -> dict[str, str]:
    seller_id = ObjectId()
    now = to_utc_naive(utc_now())
    doc = {
        "_id": seller_id,
        "status": "approved",
        "store_name": f"TEST QvaPay plan {seller_id}",
        "store_slug": f"test-qvapay-plan-{seller_id}",
        "transfer_id": f"TEST-QVAPAY-PLAN-{seller_id}",
        "phone": f"{(int(str(seller_id), 16) % 90000000) + 10000000:08d}",
        "email": f"seller-{seller_id}@qvapay-plan-e2e.test",
        "billing_period": "monthly",
        "plan_tier": "standard",
        "is_trial": False,
        "subscription_starts_at": None,
        "subscription_ends_at": None,
        "created_at": now,
        "updated_at": now,
        PLAN_MARKER: True,
    }
    await get_registrations_collection().insert_one(doc)
    return {"seller_id": str(seller_id), "store_name": doc["store_name"]}


def sign_webhook(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
