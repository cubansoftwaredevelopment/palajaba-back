"""Checkout QvaPay de publicidad, webhook, libro y OTP +53."""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.advertising.service import invoice_amounts
from app.config import settings
from app.notifications.otp_manager import can_send_sms, send_otp
from app.notifications.otp_manager.nox_provider import OtpSendResult
from app.payments.qvapay import QvaPayInvoice
from test_e2e.advertising.utils.fixtures import cleanup_db, seed_admin_contact_db, seed_seller
from test_e2e.products.utils.fixtures import cleanup_db as cleanup_product_sellers
from test_e2e.products.utils.fixtures import headers_for
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured, run_db

SECRET = "qvapay-e2e-secret"


def _sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _fake_invoice(
    *,
    amount: float,
    description: str,
    remote_id: str,
    products=None,
) -> QvaPayInvoice:
    _fake_invoice.last_products = list(products or [])
    _fake_invoice.last_description = description
    return QvaPayInvoice(
        url=f"https://qvapay.com/pay/{remote_id}",
        transaction_uuid=f"tx-{remote_id}",
        amount=amount,
        remote_id=remote_id,
        raw={},
    )


class OtpManagerTests(unittest.IsolatedAsyncioTestCase):
    def test_can_send_sms_only_plus_53(self) -> None:
        self.assertTrue(can_send_sms("+5351234567"))
        self.assertTrue(can_send_sms("51234567"))
        self.assertFalse(can_send_sms("+12125551234"))
        self.assertFalse(can_send_sms(""))

    async def test_send_otp_skips_sms_when_phone_is_not_cuba(self) -> None:
        with patch(
            "app.notifications.otp_manager.otp_manager.nox_provider.send_otp",
            new_callable=AsyncMock,
        ) as mocked:
            mocked.return_value = OtpSendResult(hash="email-hash")
            result = await send_otp(email="tienda@test.com", phone_e164="+12125551234")
            self.assertEqual(result.hash, "email-hash")
            mocked.assert_awaited_once()
            kwargs = mocked.await_args.kwargs
            self.assertEqual(kwargs["email"], "tienda@test.com")
            self.assertIsNone(kwargs["phone_e164"])

    async def test_send_otp_phone_only_rejects_non_cuba(self) -> None:
        with patch(
            "app.notifications.otp_manager.otp_manager.nox_provider.send_otp",
            new_callable=AsyncMock,
        ) as mocked:
            with self.assertRaises(Exception) as caught:
                await send_otp(phone_e164="+12125551234")
            mocked.assert_not_awaited()
            self.assertEqual(caught.exception.status_code, 400)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdvertisingE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_product_sellers()
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()
        cleanup_product_sellers()

    def test_invoice_includes_exchange_fee(self) -> None:
        plan, fee, total = invoice_amounts(15)
        self.assertEqual(plan, 15.0)
        self.assertEqual(fee, 0.08)
        self.assertEqual(total, 15.08)

    def test_checkout_webhook_ledger_and_idempotent_sms(self) -> None:
        seller = seed_seller()
        seed_admin_contact_db()
        sms = AsyncMock(return_value={"success": True})

        with (
            patch.object(settings, "qvapay_app_id", "app-e2e"),
            patch.object(settings, "qvapay_app_secret", SECRET),
            patch("app.advertising.service.create_invoice", side_effect=_fake_invoice),
            patch("app.advertising.service.send_custom_sms", sms),
            api_client() as client,
        ):
            public = client.get("/api/platform/advertising-plans")
            self.assertEqual(public.status_code, 200, public.text)
            ads10 = next(item for item in public.json()["plans"] if item["id"] == "ads-10")
            self.assertEqual(ads10["invoice_amount_usd"], 15.08)

            started = client.post(
                "/api/advertising/checkout",
                headers=headers_for(seller),
                json={"plan_id": "ads-10"},
            )
            self.assertEqual(started.status_code, 200, started.text)
            body = started.json()
            self.assertEqual(body["invoice_amount_usd"], 15.08)
            self.assertEqual(body["exchange_fee_usd"], 0.08)
            self.assertTrue(body["payment_url"].startswith("https://qvapay.com/pay/"))
            self.assertIn("Plan 1 10 días", _fake_invoice.last_description)
            self.assertEqual(
                _fake_invoice.last_products,
                [
                    {
                        "name": "Publicidad Plan 1 10 días",
                        "price": 15.08,
                    },
                ],
            )
            purchase_id = body["purchase_id"]

            payload = {
                "status": "paid",
                "remote_id": purchase_id,
                "transaction_uuid": f"tx-{purchase_id}",
            }
            raw = json.dumps(payload).encode("utf-8")
            bad = client.post(
                "/api/payments/qvapay/webhook",
                content=raw,
                headers={"content-type": "application/json", "x-qvapay-signature": "sha256=dead"},
            )
            self.assertEqual(bad.status_code, 401, bad.text)

            paid = client.post(
                "/api/payments/qvapay/webhook",
                content=raw,
                headers={"content-type": "application/json", "x-qvapay-signature": _sign(raw)},
            )
            self.assertEqual(paid.status_code, 200, paid.text)

            again = client.post(
                "/api/payments/qvapay/webhook",
                content=raw,
                headers={"content-type": "application/json", "x-qvapay-signature": _sign(raw)},
            )
            self.assertEqual(again.status_code, 200, again.text)

        self.assertEqual(sms.await_count, 2)
        phones = {call.kwargs["phone_e164"] for call in sms.await_args_list}
        self.assertEqual(phones, {"+5355511122", "+5355511133"})

        def _assert_ledger() -> None:
            async def work():
                from app.database import get_finance_ledger_collection

                docs = await get_finance_ledger_collection().find(
                    {"source": "advertising", "source_id": purchase_id}
                ).to_list(length=10)
                return docs

            return run_db(work)

        docs = _assert_ledger()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["kind"], "income")
        self.assertEqual(docs[0]["currency"], "USD")
        self.assertEqual(float(docs[0]["amount"]), 15.08)
