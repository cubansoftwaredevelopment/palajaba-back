"""Una disputa por pedido, cierre al aceptar y fallo sin doble transferencia."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.auth.utils import create_customer_token
from app.config import settings
from app.database import get_disputes_collection, get_orders_collection
from app.payments.qvapay import QvaPayInvoice
from test_e2e.payments.utils.fixtures import MARKER, SECRET, cleanup, seed_order, sign_webhook
from test_e2e.products.utils.fixtures import seed_seller
from test_e2e.utils.api import admin_auth_headers, api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db


async def cleanup_disputes() -> None:
    orders = await get_orders_collection().find({MARKER: True}, {"_id": 1}).to_list(length=None)
    ids = [doc["_id"] for doc in orders]
    if ids:
        await get_disputes_collection().delete_many({"order_id": {"$in": ids}})
    await cleanup()


def _headers(seeded, seller):
    return (
        {"Authorization": f"Bearer {create_customer_token(customer_id=seeded['customer_id'], full_name='Cliente E2E')}"},
        seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"]),
    )


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class EvidenceDisputeE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_db(cleanup_disputes)

    @classmethod
    def tearDownClass(cls) -> None:
        run_db(cleanup_disputes)

    def _reject_paid_order(self, client, seller, seeded):
        customer_headers, seller_headers = _headers(seeded, seller)
        verify = client.put("/api/auth/me/payment-methods/qvapay", headers=seller_headers, json={"username": "tiendae2e"})
        self.assertEqual(verify.status_code, 200, verify.text)
        accepted = client.post(
            f"/api/auth/me/orders/{seeded['order_id']}/qvapay/accept",
            headers=seller_headers,
            json={"delivery_price": 400, "delivery_currency": "CUP"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        webhook = json.dumps({
            "remote_id": f"store-order-{seeded['order_id']}",
            "transaction_uuid": "tx-dispute",
            "status": "paid",
        }).encode()
        hooked = client.post(
            "/api/payments/qvapay/webhook",
            content=webhook,
            headers={"x-qvapay-signature": sign_webhook(webhook), "content-type": "application/json"},
        )
        self.assertEqual(hooked.status_code, 200, hooked.text)
        content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Entrega"}]}]}
        sent = client.post(f"/api/auth/me/orders/{seeded['order_id']}/evidence", headers=seller_headers, json={"content": content})
        self.assertEqual(sent.status_code, 200, sent.text)
        rejected = client.post(f"/api/customers/me/orders/{seeded['order_id']}/qvapay/evidence/reject", headers=customer_headers)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        return customer_headers, seller_headers, content

    def test_both_parties_share_one_dispute_and_acceptance_closes_it(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))

        async def fake_invoice(**kwargs):
            return QvaPayInvoice("https://qvapay.com/pay/dispute", "tx-dispute", 3.41, kwargs["remote_id"], {})

        with patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-e2e"), \
             patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 400}), \
             patch("app.payments.service.create_invoice", new_callable=AsyncMock, side_effect=fake_invoice), \
             patch("app.payments.service.verify_qvapay_username", new_callable=AsyncMock, return_value="tiendae2e"), \
             patch("app.payments.service.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.service.transfer_to_user", new_callable=AsyncMock, return_value="transfer-accept") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             patch("app.live.hub.publish_customer_notification", new_callable=AsyncMock), \
             api_client() as client:
            customer_headers, seller_headers, content = self._reject_paid_order(client, seller, seeded)
            buyer = client.post(
                f"/api/customers/me/orders/{seeded['order_id']}/disputes",
                headers=customer_headers,
                json={"text": "No recibí el pedido."},
            )
            store = client.post(
                f"/api/auth/me/orders/{seeded['order_id']}/disputes",
                headers=seller_headers,
                json={"text": "Sí entregué el pedido."},
            )
            self.assertEqual(buyer.status_code, 200, buyer.text)
            self.assertEqual(store.status_code, 200, store.text)
            self.assertEqual(buyer.json()["id"], store.json()["id"])
            self.assertEqual(sorted(store.json()["opened_by"]), ["buyer", "seller"])
            detail = client.get(f"/api/admin/disputes/{buyer.json()['id']}", headers=admin_auth_headers())
            self.assertEqual(detail.status_code, 200, detail.text)
            reports = {item["party"]: item["text"] for item in detail.json()["reports"]}
            self.assertEqual(reports["buyer"], "No recibí el pedido.")
            self.assertEqual(reports["seller"], "Sí entregué el pedido.")
            repeat = client.post(
                f"/api/customers/me/orders/{seeded['order_id']}/disputes",
                headers=customer_headers,
                json={"text": "Otro motivo que no debe reemplazar el primero."},
            )
            self.assertEqual(repeat.status_code, 200, repeat.text)
            self.assertTrue(repeat.json()["already_reported"])
            buyer_report = next(item for item in repeat.json()["reports"] if item["party"] == "buyer")
            self.assertEqual(buyer_report["text"], "No recibí el pedido.")
            count = client.get("/api/admin/disputes/open-count", headers=admin_auth_headers())
            self.assertEqual(count.status_code, 200, count.text)
            self.assertGreaterEqual(count.json()["count"], 1)
            resent = client.post(
                f"/api/auth/me/orders/{seeded['order_id']}/evidence",
                headers=seller_headers,
                json={"content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Segunda entrega"}]}]}},
            )
            self.assertEqual(resent.status_code, 200, resent.text)
            accepted = client.post(f"/api/customers/me/orders/{seeded['order_id']}/qvapay/evidence/accept", headers=customer_headers)
            self.assertEqual(accepted.status_code, 200, accepted.text)
            transfer.assert_awaited_once()
            again = client.post(
                f"/api/customers/me/orders/{seeded['order_id']}/disputes",
                headers=customer_headers,
                json={"text": "Sigue sin llegarme."},
            )
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(again.json()["id"], buyer.json()["id"])
            self.assertEqual(again.json()["status"], "resolved")
            listed = client.get("/api/admin/disputes", headers=admin_auth_headers())
            self.assertEqual(sum(1 for item in listed.json() if item["order_id"] == seeded["order_id"]), 1)
            closed = client.get("/api/admin/disputes/open-count", headers=admin_auth_headers())
            self.assertEqual(closed.json()["count"], count.json()["count"] - 1)

        stored = run_db(lambda: get_orders_collection().find_one({"_id": ObjectId(seeded["order_id"])}))
        history = stored["qvapay"]["evidence_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "rejected")
        self.assertEqual(history[0]["content"], content)
        self.assertEqual(stored["qvapay"]["evidence"]["content"]["content"][0]["content"][0]["text"], "Segunda entrega")
        self.assertTrue(stored["qvapay"]["buyer_support_reported"])
        self.assertTrue(stored["qvapay"]["seller_support_reported"])

    def test_admin_ruling_transfers_once(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))
        run_db(lambda: get_orders_collection().update_one(
            {"_id": ObjectId(seeded["order_id"])},
            {"$set": {"qvapay.buyer_username": "cliente2e"}},
        ))

        async def fake_invoice(**kwargs):
            return QvaPayInvoice("https://qvapay.com/pay/ruling", "tx-dispute", 3.41, kwargs["remote_id"], {})

        with patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-e2e"), \
             patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 400}), \
             patch("app.payments.service.create_invoice", new_callable=AsyncMock, side_effect=fake_invoice), \
             patch("app.payments.service.verify_qvapay_username", new_callable=AsyncMock, return_value="tiendae2e"), \
             patch("app.payments.service.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.disputes.transfer_to_user", new_callable=AsyncMock, return_value="transfer-ruling") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             patch("app.live.hub.publish_customer_notification", new_callable=AsyncMock), \
             api_client() as client:
            customer_headers, seller_headers, _content = self._reject_paid_order(client, seller, seeded)
            opened = client.post(
                f"/api/customers/me/orders/{seeded['order_id']}/disputes",
                headers=customer_headers,
                json={"text": "No recibí el pedido."},
            )
            self.assertEqual(opened.status_code, 200, opened.text)
            dispute_id = opened.json()["id"]
            ruled = client.post(
                f"/api/admin/disputes/{dispute_id}/ruling",
                headers=admin_auth_headers(),
                json={"winner": "seller", "reason": "La evidencia demuestra la entrega."},
            )
            self.assertEqual(ruled.status_code, 200, ruled.text)
            self.assertEqual(ruled.json()["status"], "resolved")
            self.assertEqual(ruled.json()["winner"], "seller")
            self.assertEqual(ruled.json()["rulings"][0]["outcome"], "completed")
            self.assertEqual(ruled.json()["rulings"][0]["winner"], "seller")
            self.assertEqual(ruled.json()["rulings"][0]["store_payout_usd"], 2.0)
            self.assertEqual(ruled.json()["rulings"][0]["reason"], "La evidencia demuestra la entrega.")
            seller_orders = client.get("/api/auth/me/orders", headers=seller_headers)
            self.assertEqual(seller_orders.status_code, 200, seller_orders.text)
            settled = next(item for item in seller_orders.json()["items"] if item["id"] == seeded["order_id"])
            self.assertEqual(settled["status"], "completed")
            self.assertEqual(settled["qvapay"]["dispute_winner"], "seller")
            customer_notes = client.get("/api/customers/me/notifications", headers=customer_headers)
            seller_notes = client.get("/api/auth/me/notifications", headers=seller_headers)
            self.assertTrue(any("a favor de la tienda" in item["content"] and "realizado" in item["content"] for item in customer_notes.json()))
            self.assertTrue(any("a favor de la tienda" in item["content"] and "realizado" in item["content"] for item in seller_notes.json()))
            transfer.assert_awaited_once()
            self.assertEqual(transfer.await_args.kwargs["amount"], 2.0)
            self.assertEqual(transfer.await_args.kwargs["idempotency_key"], f"store-order-{seeded['order_id']}-release")
            duplicate = client.post(
                f"/api/admin/disputes/{dispute_id}/ruling",
                headers=admin_auth_headers(),
                json={"winner": "buyer", "reason": "Otro motivo que no debe transferir."},
            )
            self.assertEqual(duplicate.status_code, 409, duplicate.text)
            transfer.assert_awaited_once()
            later = client.post(
                f"/api/auth/me/orders/{seeded['order_id']}/disputes",
                headers=seller_headers,
                json={"text": "La entrega está hecha."},
            )
            self.assertEqual(later.json()["id"], dispute_id)
            self.assertEqual(later.json()["status"], "resolved")
            listed = client.get("/api/admin/disputes", headers=admin_auth_headers())
            self.assertEqual(sum(1 for item in listed.json() if item["order_id"] == seeded["order_id"]), 1)

    def test_buyer_ruling_cancels_the_order_and_notifies_both(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))
        run_db(lambda: get_orders_collection().update_one(
            {"_id": ObjectId(seeded["order_id"])},
            {"$set": {"qvapay.buyer_username": "cliente2e"}},
        ))

        async def fake_invoice(**kwargs):
            return QvaPayInvoice("https://qvapay.com/pay/refund", "tx-dispute", 3.41, kwargs["remote_id"], {})

        with patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-e2e"), \
             patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 400}), \
             patch("app.payments.service.create_invoice", new_callable=AsyncMock, side_effect=fake_invoice), \
             patch("app.payments.service.verify_qvapay_username", new_callable=AsyncMock, return_value="tiendae2e"), \
             patch("app.payments.service.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.disputes.transfer_to_user", new_callable=AsyncMock, return_value="transfer-refund") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             patch("app.live.hub.publish_customer_notification", new_callable=AsyncMock), \
             api_client() as client:
            customer_headers, seller_headers, _content = self._reject_paid_order(client, seller, seeded)
            opened = client.post(
                f"/api/customers/me/orders/{seeded['order_id']}/disputes",
                headers=customer_headers,
                json={"text": "No recibí el pedido."},
            )
            self.assertEqual(opened.status_code, 200, opened.text)
            ruled = client.post(
                f"/api/admin/disputes/{opened.json()['id']}/ruling",
                headers=admin_auth_headers(),
                json={"winner": "buyer", "reason": "La tienda no demostró la entrega."},
            )
            self.assertEqual(ruled.status_code, 200, ruled.text)
            self.assertEqual(ruled.json()["winner"], "buyer")
            self.assertEqual(ruled.json()["rulings"][0]["outcome"], "completed")
            self.assertEqual(ruled.json()["rulings"][0]["winner"], "buyer")
            self.assertEqual(ruled.json()["rulings"][0]["reason"], "La tienda no demostró la entrega.")
            self.assertEqual(transfer.await_args.kwargs["idempotency_key"], f"store-order-{seeded['order_id']}-refund-1")
            seller_orders = client.get("/api/auth/me/orders", headers=seller_headers)
            settled = next(item for item in seller_orders.json()["items"] if item["id"] == seeded["order_id"])
            self.assertEqual(settled["status"], "cancelled")
            self.assertEqual(settled["qvapay"]["dispute_winner"], "buyer")
            customer_notes = client.get("/api/customers/me/notifications", headers=customer_headers)
            seller_notes = client.get("/api/auth/me/notifications", headers=seller_headers)
            self.assertTrue(any("a favor del cliente" in item["content"] and "cancelado" in item["content"] for item in customer_notes.json()))
            self.assertTrue(any("a favor del cliente" in item["content"] and "cancelado" in item["content"] for item in seller_notes.json()))
