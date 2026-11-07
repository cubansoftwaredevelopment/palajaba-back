"""E2E del cobro QvaPay que activa la tienda al confirmarse el plan."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.config import settings
from app.notifications.otp_manager.nox_provider import OtpSendResult
from app.payments.qvapay import QvaPayInvoice
from test_e2e.payments.utils.fixtures import (
    SECRET,
    cleanup_plan_purchases,
    seed_inactive_plan_seller,
    sign_webhook,
)
from test_e2e.utils.api import api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class QvaPaySubscriptionE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_db(cleanup_plan_purchases)

    @classmethod
    def tearDownClass(cls) -> None:
        run_db(cleanup_plan_purchases)

    def test_paid_qvapay_plan_activates_store_and_duplicate_webhook_is_idempotent(self) -> None:
        seller = run_db(seed_inactive_plan_seller)
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        invoice = QvaPayInvoice(
            "https://qvapay.com/pay/plan-e2e",
            "plan-tx-e2e",
            10.0,
            "",
            {},
        )
        plan_prices = SimpleNamespace(
            get_price=lambda _tier, _period: SimpleNamespace(amount=10, currency="USD")
        )

        with patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-plan-e2e"), \
             patch("app.payments.subscription_service.qvapay_configured", return_value=True), \
             patch("app.payments.subscription_service.snapshot_cup_per_unit", return_value={"USD": 400, "CUP": 1}), \
             patch("app.payments.subscription_service.get_plan_prices", new_callable=AsyncMock, return_value=plan_prices), \
             patch("app.admin.service.get_platform_settings", new_callable=AsyncMock, return_value=SimpleNamespace(qvapay_plan_discount_percent=0)), \
             patch("app.payments.subscription_service.create_invoice", new_callable=AsyncMock, return_value=invoice) as create_invoice, \
             patch("app.payments.subscription_service.record_subscription_payment", new_callable=AsyncMock) as record_payment, \
             api_client() as client:
            created = client.post(
                "/api/auth/me/subscriptions/qvapay",
                headers=seller_headers,
                json={"plan_tier": "pro", "billing_period": "quarterly"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            checkout = created.json()
            self.assertEqual(checkout["invoice_amount_usd"], 10)
            self.assertEqual(checkout["status"], "pending")
            create_invoice.assert_awaited_once()

            invoice.remote_id = f"subscription-plan-{checkout['purchase_id']}"
            webhook = json.dumps({
                "remote_id": invoice.remote_id,
                "transaction_uuid": invoice.transaction_uuid,
                "status": "paid",
            }).encode()
            headers = {
                "x-qvapay-signature": sign_webhook(webhook),
                "content-type": "application/json",
            }
            first = client.post("/api/payments/qvapay/webhook", content=webhook, headers=headers)
            second = client.post("/api/payments/qvapay/webhook", content=webhook, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(second.status_code, 200, second.text)

            profile = client.get("/api/auth/me", headers=seller_headers)
            self.assertEqual(profile.status_code, 200, profile.text)
            self.assertTrue(profile.json()["subscription_active"])
            self.assertEqual(profile.json()["plan_tier"], "pro")
            self.assertEqual(profile.json()["billing_period"], "quarterly")

            purchase = client.get(
                f"/api/auth/me/subscriptions/qvapay/{checkout['purchase_id']}",
                headers=seller_headers,
            )
            self.assertEqual(purchase.status_code, 200, purchase.text)
            self.assertEqual(purchase.json()["status"], "paid")
            record_payment.assert_awaited_once()
            self.assertEqual(record_payment.await_args.kwargs["external_payment_id"], f"qvapay-plan-{checkout['purchase_id']}")

    def test_qvapay_plan_discount_reduces_the_invoice(self) -> None:
        seller = run_db(seed_inactive_plan_seller)
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        invoice = QvaPayInvoice("https://qvapay.com/pay/plan-discount", "plan-discount-e2e", 9.0, "", {})
        plan_prices = SimpleNamespace(
            get_price=lambda _tier, _period: SimpleNamespace(amount=10, currency="USD")
        )
        with patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-plan-discount"), \
             patch("app.payments.subscription_service.qvapay_configured", return_value=True), \
             patch("app.payments.subscription_service.snapshot_cup_per_unit", return_value={"USD": 400, "CUP": 1}), \
             patch("app.payments.subscription_service.get_plan_prices", new_callable=AsyncMock, return_value=plan_prices), \
             patch("app.admin.service.get_platform_settings", new_callable=AsyncMock, return_value=SimpleNamespace(qvapay_plan_discount_percent=10)), \
             patch("app.payments.subscription_service.create_invoice", new_callable=AsyncMock, return_value=invoice) as create_invoice, \
             api_client() as client:
            created = client.post(
                "/api/auth/me/subscriptions/qvapay",
                headers=seller_headers,
                json={"plan_tier": "pro", "billing_period": "monthly"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["invoice_amount_usd"], 9)
            self.assertEqual(created.json()["plan_amount_usd"], 10)
            self.assertEqual(create_invoice.await_args.kwargs["amount"], 9)

    def test_initial_plan_payment_must_be_confirmed_before_registration_and_activates_account(self) -> None:
        invoice = QvaPayInvoice("https://qvapay.com/pay/signup-e2e", "signup-tx-e2e", 10.0, "", {})
        plan_prices = SimpleNamespace(
            get_price=lambda _tier, _period: SimpleNamespace(amount=10, currency="USD")
        )
        with patch.multiple(
            settings,
            qvapay_app_secret=SECRET,
            qvapay_app_id="app-signup-e2e",
        ), \
             patch("app.payments.subscription_service.qvapay_configured", return_value=True), \
             patch("app.payments.subscription_service.snapshot_cup_per_unit", return_value={"USD": 400, "CUP": 1}), \
             patch("app.payments.subscription_service.get_plan_prices", new_callable=AsyncMock, return_value=plan_prices), \
             patch("app.admin.service.get_platform_settings", new_callable=AsyncMock, return_value=SimpleNamespace(qvapay_plan_discount_percent=0)), \
             patch("app.payments.subscription_service.create_invoice", new_callable=AsyncMock, return_value=invoice), \
             patch("app.payments.subscription_service.record_subscription_payment", new_callable=AsyncMock), \
             patch("app.auth.service.send_otp", new_callable=AsyncMock, return_value=OtpSendResult(hash="otp-e2e", expires_at="2030-01-01T00:00:00+00:00", message="test")), \
             patch("app.auth.service.verify_otp", new_callable=AsyncMock), \
             api_client() as client:
            created = client.post(
                "/api/register/qvapay",
                json={"plan_tier": "pro", "billing_period": "quarterly"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            checkout = created.json()
            invoice.remote_id = f"subscription-plan-{checkout['purchase_id']}"
            registration = {
                "kind": "account",
                "qvapay_purchase_id": checkout["purchase_id"],
                "plan_tier": "pro",
                "billing_period": "quarterly",
                "store_name": "Tienda alta QvaPay E2E",
                "email": f"signup-{checkout['purchase_id']}@qvapay-plan-e2e.test",
                "phone": f"{(int(checkout['purchase_id'], 16) % 90000000) + 10000000:08d}",
                "password": "clave123",
                "accepted_terms": True,
            }
            unpaid = client.post("/api/register/otp/start", json=registration)
            self.assertEqual(unpaid.status_code, 409, unpaid.text)

            body = json.dumps({
                "remote_id": invoice.remote_id,
                "transaction_uuid": invoice.transaction_uuid,
                "status": "paid",
            }).encode()
            webhook = client.post(
                "/api/payments/qvapay/webhook",
                content=body,
                headers={"x-qvapay-signature": sign_webhook(body), "content-type": "application/json"},
            )
            self.assertEqual(webhook.status_code, 200, webhook.text)
            started = client.post("/api/register/otp/start", json=registration)
            self.assertEqual(started.status_code, 200, started.text)
            confirmed = client.post(
                "/api/register/otp/confirm",
                json={"challenge_id": started.json()["challenge_id"], "email_code": "000000", "phone_code": "000000"},
            )
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            self.assertTrue(confirmed.json()["access_token"])

            profile = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {confirmed.json()['access_token']}"},
            )
            self.assertEqual(profile.status_code, 200, profile.text)
            self.assertTrue(profile.json()["subscription_active"])
            self.assertEqual(profile.json()["plan_tier"], "pro")
