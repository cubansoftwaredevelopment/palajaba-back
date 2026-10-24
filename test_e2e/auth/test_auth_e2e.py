"""Recorrido HTTP de registro, login y recuperación de contraseña."""

from __future__ import annotations

import unittest

from bson import ObjectId

from test_e2e.auth.utils.fixtures import (
    EMAIL_CODE,
    PHONE_CODE,
    cleanup_db,
    patch_otp,
    seed_seller,
    store_name,
    unique_email,
    unique_phone,
)
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AuthE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_login_with_phone_and_store_name(self) -> None:
        seller = seed_seller()

        with api_client() as client:
            by_phone = client.post(
                "/api/auth/login",
                json={
                    "method": "phone",
                    "phone": seller["phone"],
                    "password": seller["password"],
                },
            )
            by_store = client.post(
                "/api/auth/login",
                json={
                    "method": "store_name",
                    "store_name": seller["store_name"],
                    "password": seller["password"],
                },
            )
            wrong = client.post(
                "/api/auth/login",
                json={
                    "method": "phone",
                    "phone": seller["phone"],
                    "password": "otra-clave",
                },
            )

        self.assertEqual(by_phone.status_code, 200, by_phone.text)
        self.assertTrue(by_phone.json()["access_token"])
        self.assertEqual(by_phone.json()["seller"]["id"], seller["seller_id"])
        self.assertIsNone(by_phone.json().get("subscription_expired"))

        self.assertEqual(by_store.status_code, 200, by_store.text)
        self.assertEqual(by_store.json()["seller"]["store_name"], seller["store_name"])

        self.assertEqual(wrong.status_code, 401, wrong.text)
        self.assertEqual(wrong.json()["detail"], "Credenciales incorrectas.")

    def test_login_returns_expired_payload_when_subscription_ended(self) -> None:
        seller = seed_seller(subscription_days=-2)

        with api_client() as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "method": "phone",
                    "phone": seller["phone"],
                    "password": seller["password"],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["access_token"])
        self.assertEqual(body["subscription_expired"]["code"], "subscription_expired")
        self.assertEqual(body["subscription_expired"]["store_name"], seller["store_name"])

    def test_trial_register_otp_creates_store_and_allows_login(self) -> None:
        seller_id = ObjectId()
        payload = {
            "kind": "trial",
            "store_name": store_name(str(seller_id)),
            "email": unique_email(str(seller_id)),
            "phone": unique_phone(seller_id),
            "password": "nueva123",
        }

        with patch_otp(), api_client() as client:
            started = client.post("/api/register/otp/start", json=payload)
            self.assertEqual(started.status_code, 200, started.text)
            challenge_id = started.json()["challenge_id"]

            bad_code = client.post(
                "/api/register/otp/confirm",
                json={
                    "challenge_id": challenge_id,
                    "email_code": "000000",
                    "phone_code": PHONE_CODE,
                },
            )
            self.assertEqual(bad_code.status_code, 400, bad_code.text)

            confirmed = client.post(
                "/api/register/otp/confirm",
                json={
                    "challenge_id": challenge_id,
                    "email_code": EMAIL_CODE,
                    "phone_code": PHONE_CODE,
                },
            )
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            body = confirmed.json()
            self.assertEqual(body["kind"], "trial")
            self.assertEqual(body["status"], "approved")
            self.assertTrue(body["access_token"])

            login = client.post(
                "/api/auth/login",
                json={
                    "method": "phone",
                    "phone": payload["phone"],
                    "password": payload["password"],
                },
            )

        self.assertEqual(login.status_code, 200, login.text)
        seller = login.json()["seller"]
        self.assertTrue(seller["is_trial"])
        self.assertEqual(seller["plan_tier"], "standard")
        self.assertTrue(seller["has_product_discounts"])
        self.assertTrue(seller["has_statistics"])
        self.assertFalse(seller["has_full_store_customization"])

    def test_password_reset_otp_then_login_with_new_password(self) -> None:
        seller = seed_seller()

        with patch_otp(), api_client() as client:
            started = client.post(
                "/api/auth/password-reset/start",
                json={"method": "phone", "phone": seller["phone"]},
            )
            self.assertEqual(started.status_code, 200, started.text)
            challenge_id = started.json()["challenge_id"]
            self.assertIn("****", started.json()["phone_hint"])

            resent = client.post(
                "/api/auth/password-reset/otp/resend",
                json={"challenge_id": challenge_id, "channel": "phone"},
            )
            self.assertEqual(resent.status_code, 200, resent.text)

            confirmed = client.post(
                "/api/auth/password-reset/otp/confirm",
                json={
                    "challenge_id": challenge_id,
                    "email_code": EMAIL_CODE,
                    "phone_code": PHONE_CODE,
                },
            )
            self.assertEqual(confirmed.status_code, 200, confirmed.text)

            completed = client.post(
                "/api/auth/password-reset/complete",
                json={"challenge_id": challenge_id, "password": "cambiada9"},
            )
            self.assertEqual(completed.status_code, 200, completed.text)

            old_password = client.post(
                "/api/auth/login",
                json={
                    "method": "phone",
                    "phone": seller["phone"],
                    "password": seller["password"],
                },
            )
            new_password = client.post(
                "/api/auth/login",
                json={
                    "method": "phone",
                    "phone": seller["phone"],
                    "password": "cambiada9",
                },
            )

        self.assertEqual(old_password.status_code, 401, old_password.text)
        self.assertEqual(new_password.status_code, 200, new_password.text)
        self.assertEqual(new_password.json()["seller"]["id"], seller["seller_id"])

    def test_password_reset_unknown_account_is_not_found(self) -> None:
        with api_client() as client:
            response = client.post(
                "/api/auth/password-reset/start",
                json={"method": "phone", "phone": "89999999"},
            )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "No encontramos una cuenta con esos datos.")
