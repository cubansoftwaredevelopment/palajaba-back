"""E2E del cobro QvaPay retenido hasta resolver la evidencia de entrega."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.auth.utils import create_customer_token
from app.config import settings
from app.database import get_orders_collection, get_server_heartbeat_collection
from app.payments.evidence_clock import CLOCK_ID, record_server_heartbeat
from app.payments.qvapay import QvaPayInvoice
from app.payments.service import expire_due_evidence
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.payments.utils.fixtures import SECRET, cleanup, seed_order, sign_webhook
from test_e2e.products.utils.fixtures import seed_seller
from test_e2e.utils.api import api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db

@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class QvaPayEscrowE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_db(cleanup)

    @classmethod
    def tearDownClass(cls) -> None:
        run_db(cleanup)

    def test_paid_order_stays_held_until_customer_accepts_and_rejection_allows_new_evidence(self) -> None:
        seller = seed_seller(plan_tier="basic")
        seeded = run_db(lambda: seed_order(seller["seller_id"]))
        customer_headers = {"Authorization": f"Bearer {create_customer_token(customer_id=seeded['customer_id'], full_name='Cliente E2E')}"}
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        invoice = QvaPayInvoice("https://qvapay.com/pay/e2e", "tx-e2e", 3.41,
                                f"store-order-{seeded['order_id']}", {})
        settings_patch = patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-e2e")
        with settings_patch, patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 400}), \
             patch("app.admin.service.get_platform_settings", new_callable=AsyncMock, return_value=SimpleNamespace(transaction_fee_percent=10)), \
             patch("app.payments.service.create_invoice", new_callable=AsyncMock, return_value=invoice) as create_invoice, \
             patch("app.payments.service.verify_qvapay_username", new_callable=AsyncMock, return_value="tiendae2e"), \
             patch("app.payments.service.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.service.transfer_to_user", new_callable=AsyncMock, return_value="transfer-e2e") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             api_client() as client:
            verify = client.put("/api/auth/me/payment-methods/qvapay", headers=seller_headers,
                                json={"username": "tiendae2e"})
            self.assertEqual(verify.status_code, 200, verify.text)
            self.assertEqual(verify.json(), {"username": "tiendae2e", "verified": True})

            accepted = client.post(f"/api/auth/me/orders/{seeded['order_id']}/qvapay/accept",
                                   headers=seller_headers, json={"delivery_price": 400, "delivery_currency": "CUP"})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(accepted.json()["invoice_amount_usd"], 2.2)
            create_invoice.assert_awaited_once()
            invoice_products = create_invoice.await_args.kwargs["products"]
            self.assertEqual([(item["name"], item["price"]) for item in invoice_products], [
                ("Arroz", 1.0), ("Domicilio", 1.0), ("fee", 0.2),
            ])
            seller_orders = client.get("/api/auth/me/orders?limit=100", headers=seller_headers)
            self.assertEqual(seller_orders.status_code, 200)
            stored = next(item for item in seller_orders.json()["items"] if item["id"] == seeded["order_id"])
            self.assertEqual(stored["qvapay"]["release_status"], "held")
            self.assertEqual(stored["qvapay"]["invoice_amount_usd"], 2.2)

            webhook = json.dumps({"remote_id": invoice.remote_id, "transaction_uuid": invoice.transaction_uuid,
                                  "status": "paid"}).encode()
            hooked = client.post("/api/payments/qvapay/webhook", content=webhook,
                                 headers={"x-qvapay-signature": sign_webhook(webhook), "content-type": "application/json"})
            self.assertEqual(hooked.status_code, 200, hooked.text)
            customer_orders = client.get("/api/customers/me/orders", headers=customer_headers)
            self.assertEqual(customer_orders.status_code, 200)
            stored = next(item for item in customer_orders.json() if item["id"] == seeded["order_id"])
            self.assertEqual(stored["payment_method"], "qvapay")
            self.assertEqual(stored["qvapay"]["payment_status"], "paid")
            self.assertEqual(stored["qvapay"]["release_status"], "held")
            transfer.assert_not_awaited()

            content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Entrega enviada"}]}]}
            sent = client.post(f"/api/auth/me/orders/{seeded['order_id']}/evidence", headers=seller_headers,
                               json={"content": content})
            self.assertEqual(sent.status_code, 200, sent.text)
            self.assertIn("No esperes", sent.json()["warning"])
            notifications = client.get("/api/customers/me/notifications", headers=customer_headers)
            self.assertEqual(notifications.status_code, 200)
            self.assertTrue(any("No esperes" in item["content"] for item in notifications.json()))
            duplicate = client.post(f"/api/auth/me/orders/{seeded['order_id']}/evidence", headers=seller_headers,
                                    json={"content": content})
            self.assertEqual(duplicate.status_code, 409)

            rejected = client.post(f"/api/customers/me/orders/{seeded['order_id']}/qvapay/evidence/reject",
                                   headers=customer_headers)
            self.assertEqual(rejected.status_code, 200, rejected.text)
            transfer.assert_not_awaited()
            resent = client.post(f"/api/auth/me/orders/{seeded['order_id']}/evidence", headers=seller_headers,
                                 json={"content": content})
            self.assertEqual(resent.status_code, 200, resent.text)
            accepted_evidence = client.post(f"/api/customers/me/orders/{seeded['order_id']}/qvapay/evidence/accept",
                                            headers=customer_headers)
            self.assertEqual(accepted_evidence.status_code, 200, accepted_evidence.text)
            transfer.assert_awaited_once_with(amount=2.0, username="tiendae2e",
                                              description=f"Liquidación pedido {seeded['order_id'][-6:].upper()}",
                                              idempotency_key=f"store-order-{seeded['order_id']}-release")
            duplicate_decision = client.post(f"/api/customers/me/orders/{seeded['order_id']}/qvapay/evidence/accept",
                                             headers=customer_headers)
            self.assertEqual(duplicate_decision.status_code, 409)
            transfer.assert_awaited_once()
            final_orders = client.get("/api/auth/me/orders?limit=100", headers=seller_headers)
            final = next(item for item in final_orders.json()["items"] if item["id"] == seeded["order_id"])
            self.assertEqual(final["qvapay"]["release_status"], "released")
            self.assertEqual(final["status"], "completed")

    def test_expired_evidence_is_accepted_and_released_once(self) -> None:
        seller = seed_seller(plan_tier="premium")
        seeded = run_db(lambda: seed_order(seller["seller_id"], deadline=to_utc_naive(utc_now()) - timedelta(seconds=1)))
        with patch("app.payments.service.transfer_to_user", new_callable=AsyncMock, return_value="transfer-expired") as transfer, \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock):
            run_db(expire_due_evidence)
            run_db(expire_due_evidence)
            transfer.assert_awaited_once()
        final = run_db(lambda: get_orders_collection().find_one({"_id": ObjectId(seeded["order_id"])}))
        self.assertEqual(final["qvapay"]["evidence"]["status"], "expired")
        self.assertEqual(final["qvapay"]["release_status"], "released")
        self.assertEqual(final["status"], "completed")

    def test_server_downtime_extends_only_pending_evidence_deadlines(self) -> None:
        seller = seed_seller(plan_tier="premium")
        deadline = to_utc_naive(utc_now()) + timedelta(hours=2)
        pending = run_db(lambda: seed_order(seller["seller_id"], deadline=deadline))
        rejected = run_db(lambda: seed_order(seller["seller_id"], deadline=deadline))

        async def mark_rejected() -> None:
            await get_orders_collection().update_one(
                {"_id": ObjectId(rejected["order_id"])},
                {"$set": {"qvapay.evidence.status": "rejected"}},
            )

        run_db(mark_rejected)

        async def apply_downtime() -> tuple[timedelta, timedelta, timedelta, timedelta, timedelta]:
            orders = get_orders_collection()
            clock = get_server_heartbeat_collection()
            pending_filter = {
                "payment_method": "qvapay",
                "qvapay.evidence.status": "pending",
                "qvapay.evidence.deadline": {"$type": "date"},
            }
            before = {
                doc["_id"]: doc["qvapay"]["evidence"]["deadline"]
                async for doc in orders.find(pending_filter, {"qvapay.evidence.deadline": 1})
            }
            rejected_before = (await orders.find_one({"_id": ObjectId(rejected["order_id"])}))["qvapay"]["evidence"]["deadline"]
            stalled_at = to_utc_naive(utc_now()) - timedelta(minutes=30)
            await clock.update_one({"_id": CLOCK_ID}, {"$set": {"beat_at": stalled_at}}, upsert=True)
            try:
                gap = await record_server_heartbeat()
                moved = (await orders.find_one({"_id": ObjectId(pending["order_id"])}))["qvapay"]["evidence"]["deadline"]
                untouched = (await orders.find_one({"_id": ObjectId(rejected["order_id"])}))["qvapay"]["evidence"]["deadline"]
                second_gap = await record_server_heartbeat()
                moved_again = (await orders.find_one({"_id": ObjectId(pending["order_id"])}))["qvapay"]["evidence"]["deadline"]
            finally:
                for order_id, previous_deadline in before.items():
                    await orders.update_one(
                        {"_id": order_id},
                        {"$set": {"qvapay.evidence.deadline": previous_deadline}},
                    )
                await clock.update_one(
                    {"_id": CLOCK_ID},
                    {"$set": {"beat_at": to_utc_naive(utc_now())}},
                    upsert=True,
                )
            return gap, second_gap, moved - before[ObjectId(pending["order_id"])], untouched - rejected_before, moved_again - moved

        gap, second_gap, shift, rejected_shift, second_shift = run_db(apply_downtime)
        self.assertGreater(gap, timedelta(minutes=29))
        self.assertEqual(second_gap, timedelta(0))
        self.assertGreater(shift, timedelta(minutes=29))
        self.assertLess(abs(shift - gap), timedelta(seconds=2))
        self.assertEqual(rejected_shift, timedelta(0))
        self.assertEqual(second_shift, timedelta(0))
