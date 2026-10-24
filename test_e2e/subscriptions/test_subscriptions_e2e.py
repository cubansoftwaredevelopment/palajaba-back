"""Recorrido de identidad de plan, prestaciones y reemplazo de suscripción."""

from __future__ import annotations

import unittest
from datetime import timedelta

from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.subscriptions.utils.fixtures import (
    cleanup_db,
    headers_for,
    load_seller,
    seed_seller,
)
from test_e2e.utils.api import admin_auth_headers, api_client
from test_e2e.utils.database import mongo_configured


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SubscriptionsE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_trial_store_is_prueba_with_pro_entitlements(self) -> None:
        trial = seed_seller(plan_tier="standard", is_trial=True)
        basic = seed_seller(plan_tier="standard")
        premium = seed_seller(plan_tier="premium")

        with api_client() as client:
            trial_me = client.get("/api/auth/me", headers=headers_for(trial))
            basic_me = client.get("/api/auth/me", headers=headers_for(basic))
            premium_me = client.get("/api/auth/me", headers=headers_for(premium))

        self.assertEqual(trial_me.status_code, 200, trial_me.text)
        trial_body = trial_me.json()
        self.assertTrue(trial_body["is_trial"])
        self.assertEqual(trial_body["plan_tier"], "standard")
        self.assertTrue(trial_body["has_product_discounts"])
        self.assertTrue(trial_body["has_statistics"])
        self.assertTrue(trial_body["has_store_banners"])
        self.assertFalse(trial_body["has_full_store_customization"])

        self.assertEqual(basic_me.status_code, 200, basic_me.text)
        basic_body = basic_me.json()
        self.assertFalse(basic_body["is_trial"])
        self.assertFalse(basic_body["has_product_discounts"])
        self.assertFalse(basic_body["has_statistics"])

        self.assertEqual(premium_me.status_code, 200, premium_me.text)
        self.assertTrue(premium_me.json()["has_full_store_customization"])
        self.assertTrue(premium_me.json()["has_product_discounts"])

    def test_admin_replaces_trial_with_basic_from_today(self) -> None:
        seller = seed_seller(plan_tier="standard", is_trial=True)

        with api_client() as client:
            updated = client.patch(
                f"/api/admin/registrations/{seller['seller_id']}/subscription",
                headers=admin_auth_headers(),
                json={
                    "plan_tier": "standard",
                    "billing_period": "monthly",
                    "keep_gestor_ids": [],
                },
            )
            me = client.get("/api/auth/me", headers=headers_for(seller))

        self.assertEqual(updated.status_code, 200, updated.text)
        body = updated.json()
        self.assertEqual(body["plan_tier"], "standard")
        self.assertEqual(body["billing_period"], "monthly")
        self.assertFalse(body["is_trial"])
        self.assertEqual(body["status"], "approved")

        self.assertEqual(me.status_code, 200, me.text)
        self.assertFalse(me.json()["is_trial"])
        self.assertFalse(me.json()["has_product_discounts"])

        stored = load_seller(seller["seller_id"])
        now = to_utc_naive(utc_now())
        self.assertFalse(stored.get("is_trial"))
        self.assertGreaterEqual(stored["subscription_starts_at"], now - timedelta(minutes=2))
        self.assertLess(stored["subscription_ends_at"], now + timedelta(days=32))
        self.assertGreater(stored["subscription_ends_at"], now + timedelta(days=20))

    def test_admin_upgrades_trial_to_premium_keeps_pro_plus_palette(self) -> None:
        seller = seed_seller(plan_tier="standard", is_trial=True)

        with api_client() as client:
            updated = client.patch(
                f"/api/admin/registrations/{seller['seller_id']}/subscription",
                headers=admin_auth_headers(),
                json={
                    "plan_tier": "premium",
                    "billing_period": "quarterly",
                    "keep_gestor_ids": [],
                },
            )
            me = client.get("/api/auth/me", headers=headers_for(seller))

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["plan_tier"], "premium")
        self.assertEqual(updated.json()["billing_period"], "quarterly")
        self.assertFalse(updated.json()["is_trial"])

        self.assertEqual(me.status_code, 200, me.text)
        me_body = me.json()
        self.assertFalse(me_body["is_trial"])
        self.assertEqual(me_body["plan_tier"], "premium")
        self.assertTrue(me_body["has_product_discounts"])
        self.assertTrue(me_body["has_full_store_customization"])
