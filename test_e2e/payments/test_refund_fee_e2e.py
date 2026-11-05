"""Tarifa porcentual y reembolso QvaPay por lo que se quita del pedido."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.auth.utils import create_customer_token
from app.database import (
    get_customer_notifications_collection,
    get_disputes_collection,
    get_orders_collection,
)
from app.payments.qvapay import QvaPayInvoice
from app.payments.service import payment_quote
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.payments.utils.fixtures import MARKER, cleanup, seed_order
from test_e2e.products.utils.fixtures import seed_seller
from test_e2e.utils.api import admin_auth_headers, api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db

REASON_IMAGE = "/uploads/refund-reasons/motivo.jpg"


class TransactionFeeQuoteTests(unittest.TestCase):
    def test_percent_fee_and_zero_percent(self) -> None:
        order = {
            "delivery_requested": True,
            "items": [{
                "name": "Arroz",
                "quantity": 1,
                "unit_price": 1,
                "currency": "USD",
                "line_total": 1,
            }],
        }
        with patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 1}):
            quoted = payment_quote(order, 1, "USD", fee_percent=10)
            zero = payment_quote(order, 1, "USD", fee_percent=0)
        self.assertEqual(quoted["products_amount_usd"], 1.0)
        self.assertEqual(quoted["delivery_amount_usd"], 1.0)
        self.assertEqual(quoted["fee_usd"], 0.2)
        self.assertEqual(quoted["invoice_amount_usd"], 2.2)
        self.assertEqual(zero["fee_usd"], 0.0)
        self.assertEqual(zero["invoice_amount_usd"], 2.0)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class RefundAndFeeE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_db(cleanup)

    @classmethod
    def tearDownClass(cls) -> None:
        run_db(_cleanup)

    def test_zero_percent_omits_the_fee_line(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        invoice = QvaPayInvoice("https://qvapay.com/pay/fee0", "tx-fee0", 2.0, f"store-order-{seeded['order_id']}", {})
        with patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 400}), \
             patch("app.admin.service.get_platform_settings", new_callable=AsyncMock, return_value=SimpleNamespace(transaction_fee_percent=0)), \
             patch("app.payments.service.create_invoice", new_callable=AsyncMock, return_value=invoice) as create_invoice, \
             patch("app.payments.service.verify_qvapay_username", new_callable=AsyncMock, return_value="tiendae2e"), \
             patch("app.payments.service.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             api_client() as client:
            client.put("/api/auth/me/payment-methods/qvapay", headers=seller_headers, json={"username": "tiendae2e"})
            accepted = client.post(
                f"/api/auth/me/orders/{seeded['order_id']}/qvapay/accept",
                headers=seller_headers,
                json={"delivery_price": 400, "delivery_currency": "CUP"},
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(accepted.json()["invoice_amount_usd"], 2.0)
            names = [item["name"] for item in create_invoice.await_args.kwargs["products"]]
            self.assertNotIn("fee", names)

    def test_store_refund_returns_the_removed_slice_and_keeps_the_rest_held(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))
        delivery_order = run_db(lambda: seed_order(seller["seller_id"]))
        run_db(lambda: _mark_paid(seeded["order_id"]))
        run_db(lambda: _mark_paid(delivery_order["order_id"]))
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        customer_headers = {"Authorization": f"Bearer {create_customer_token(customer_id=seeded['customer_id'], full_name='Cliente E2E')}"}
        with patch("app.payments.refunds.transfer_to_user", new_callable=AsyncMock, return_value="refund-tx") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock) as sms, \
             patch("app.live.hub.publish_customer_notification", new_callable=AsyncMock), \
             api_client() as client:
            partial = client.post(
                f"/api/auth/me/orders/{seeded['order_id']}/qvapay/refund",
                headers=seller_headers,
                json={
                    "items": [{"product_id": "producto-e2e", "quantity": 1}],
                    "refund_delivery": False,
                    "text": "Llegó dañado",
                    "images": [REASON_IMAGE],
                },
            )
            self.assertEqual(partial.status_code, 200, partial.text)
            self.assertEqual(partial.json()["refund_amount_usd"], 44.0)
            self.assertEqual(partial.json()["release_status"], "held")
            self.assertEqual(transfer.await_args.kwargs["amount"], 44.0)
            self.assertEqual(transfer.await_args.kwargs["idempotency_key"], f"store-order-{seeded['order_id']}-refund-1")
            sms.assert_not_awaited()
            notes = client.get("/api/customers/me/notifications", headers=customer_headers)
            self.assertEqual(notes.status_code, 200, notes.text)
            notice = next(item for item in notes.json() if item["kind"] == "qvapay_refund")
            self.assertEqual(notice["content"], "Llegó dañado")
            self.assertEqual(notice["images"], [REASON_IMAGE])
            stored = _seller_order(client, seller_headers, seeded["order_id"])
            self.assertEqual(stored["status"], "pending_confirmation")
            self.assertEqual(stored["qvapay"]["products_amount_usd"], 40.0)
            self.assertEqual(stored["qvapay"]["delivery_amount_usd"], 20.0)
            self.assertEqual(stored["qvapay"]["fee_usd"], 6.0)
            self.assertEqual(stored["items"][0]["quantity"], 1)

            delivery_only = client.post(
                f"/api/auth/me/orders/{delivery_order['order_id']}/qvapay/refund",
                headers=seller_headers,
                json={
                    "items": [{"product_id": "producto-e2e", "quantity": 2}],
                    "refund_delivery": True,
                    "text": "El domicilio no se hizo",
                    "images": [REASON_IMAGE],
                },
            )
            self.assertEqual(delivery_only.status_code, 200, delivery_only.text)
            self.assertEqual(delivery_only.json()["refund_amount_usd"], 22.0)
            held = _seller_order(client, seller_headers, delivery_order["order_id"])
            self.assertEqual(held["qvapay"]["release_status"], "held")
            self.assertEqual(held["qvapay"]["products_amount_usd"], 80.0)
            self.assertEqual(held["qvapay"]["delivery_amount_usd"], 0.0)
            self.assertEqual(held["qvapay"]["fee_usd"], 8.0)

    def test_empty_order_refunds_the_invoice_and_open_dispute_blocks_the_store(self) -> None:
        seller = seed_seller(plan_tier="basic")
        emptied = run_db(lambda: seed_order(seller["seller_id"]))
        blocked = run_db(lambda: seed_order(seller["seller_id"]))
        run_db(lambda: _mark_paid(emptied["order_id"]))
        run_db(lambda: _mark_paid(blocked["order_id"]))
        run_db(lambda: _open_dispute(blocked["order_id"]))
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        with patch("app.payments.refunds.transfer_to_user", new_callable=AsyncMock, return_value="refund-tx") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.live.hub.publish_customer_notification", new_callable=AsyncMock), \
             api_client() as client:
            full = client.post(
                f"/api/auth/me/orders/{emptied['order_id']}/qvapay/refund",
                headers=seller_headers,
                json={
                    "items": [{"product_id": "producto-e2e", "quantity": 0}],
                    "refund_delivery": True,
                    "text": "No quedó nada del pedido",
                    "images": [REASON_IMAGE],
                },
            )
            self.assertEqual(full.status_code, 200, full.text)
            self.assertEqual(full.json()["refund_amount_usd"], 110.0)
            cancelled = _seller_order(client, seller_headers, emptied["order_id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(cancelled["qvapay"]["release_status"], "refunded")
            denied = client.post(
                f"/api/auth/me/orders/{blocked['order_id']}/qvapay/refund",
                headers=seller_headers,
                json={
                    "items": [{"product_id": "producto-e2e", "quantity": 0}],
                    "refund_delivery": True,
                    "text": "No debería salir",
                    "images": [REASON_IMAGE],
                },
            )
            self.assertEqual(denied.status_code, 409, denied.text)
            self.assertEqual(transfer.await_count, 1)

    def test_admin_partial_refund_pays_the_buyer_and_releases_the_rest_to_the_store(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))
        run_db(lambda: _mark_paid(seeded["order_id"]))
        dispute_id = run_db(lambda: _open_dispute(seeded["order_id"]))
        calls = {"n": 0}

        async def transfer(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("store down")
            return f"tx-{calls['n']}"

        with patch("app.payments.disputes.transfer_to_user", new=AsyncMock(side_effect=transfer)) as transfer_mock, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             patch("app.live.hub.publish_customer_notification", new_callable=AsyncMock), \
             api_client() as client:
            ruled = client.post(
                f"/api/admin/disputes/{dispute_id}/ruling",
                headers=admin_auth_headers(),
                json={
                    "winner": "buyer",
                    "reason": "Se devuelve la mitad del producto.",
                    "refund_delivery": False,
                    "items": [{"product_id": "producto-e2e", "quantity": 1}],
                },
            )
            self.assertEqual(ruled.status_code, 503, ruled.text)
            self.assertEqual(transfer_mock.await_count, 2)
            self.assertEqual(transfer_mock.await_args_list[0].kwargs["amount"], 44.0)
            self.assertEqual(transfer_mock.await_args_list[1].kwargs["amount"], 60.0)
            self.assertEqual(transfer_mock.await_args_list[1].kwargs["idempotency_key"], f"store-order-{seeded['order_id']}-release")
            retry = client.post(
                f"/api/admin/disputes/{dispute_id}/ruling",
                headers=admin_auth_headers(),
                json={"winner": "buyer", "reason": "Reintento del pago a la tienda."},
            )
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(retry.json()["winner"], "buyer")
            self.assertEqual(transfer_mock.await_count, 3)
            self.assertEqual(transfer_mock.await_args.kwargs["amount"], 60.0)
            self.assertEqual(transfer_mock.await_args.kwargs["idempotency_key"], f"store-order-{seeded['order_id']}-release")
            seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
            stored = _seller_order(client, seller_headers, seeded["order_id"])
            self.assertEqual(stored["status"], "cancelled")
            self.assertEqual(stored["qvapay"]["store_payout_usd"], 60.0)
            self.assertEqual(stored["qvapay"]["products_amount_usd"], 40.0)
            self.assertEqual(stored["qvapay"]["delivery_amount_usd"], 20.0)


def _seller_order(client, headers, order_id: str) -> dict:
    listed = client.get("/api/auth/me/orders?limit=100", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(item for item in listed.json()["items"] if item["id"] == order_id)


async def _mark_paid(order_id: str) -> None:
    await get_orders_collection().update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {
            "qvapay.request_status": "accepted",
            "qvapay.payment_status": "paid",
            "qvapay.release_status": "held",
            "qvapay.buyer_username": "cliente2e",
            "qvapay.payout_username": "tiendae2e",
            "qvapay.products_amount_usd": 80,
            "qvapay.delivery_amount_usd": 20,
            "qvapay.fee_usd": 10,
            "qvapay.invoice_amount_usd": 110,
            "items": [{
                "product_id": "producto-e2e",
                "name": "Arroz",
                "quantity": 2,
                "unit_price": 40,
                "currency": "USD",
                "line_total": 80,
            }],
            "subtotals": [{"currency": "USD", "amount": 80}],
            "delivery_price": 20,
            "delivery_currency": "USD",
        }},
    )


async def _open_dispute(order_id: str) -> str:
    now = to_utc_naive(utc_now())
    result = await get_disputes_collection().insert_one({
        "order_id": ObjectId(order_id),
        "status": "open",
        "opened_by": ["buyer"],
        "reports": [],
        "created_at": now,
        "updated_at": now,
        MARKER: True,
    })
    return str(result.inserted_id)


async def _cleanup() -> None:
    orders = get_orders_collection()
    order_ids = [doc["_id"] async for doc in orders.find({MARKER: True}, {"_id": 1})]
    buyer_ids = []
    async for doc in orders.find({MARKER: True}, {"buyer_id": 1}):
        try:
            buyer_ids.append(ObjectId(str(doc.get("buyer_id") or "")))
        except Exception:
            continue
    await get_disputes_collection().delete_many({"$or": [{"order_id": {"$in": order_ids}}, {MARKER: True}]})
    if buyer_ids:
        await get_customer_notifications_collection().delete_many({"customer_id": {"$in": buyer_ids}})
    await cleanup()
