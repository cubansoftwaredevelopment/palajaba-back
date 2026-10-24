"""Recorrido admin: reemplazar plan/periodo y desactivar gestores que no caben."""

from __future__ import annotations

import unittest
from datetime import timedelta

from app.subscriptions.service import STANDARD_GESTOR_LIMIT
from app.subscriptions.utils import GESTOR_KEEP_LIMIT_MESSAGE
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.subscription_replace.utils.fixtures import (
    cleanup_db,
    load_seller_and_gestores,
    seed_seller_with_gestores,
)
from test_e2e.utils.api import admin_auth_headers, api_client
from test_e2e.utils.database import mongo_configured


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SubscriptionReplaceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_admin_replace_premium_with_basic_keeps_selected_gestores(self) -> None:
        seeded = seed_seller_with_gestores(plan_tier="premium", gestor_count=12)
        keep_ids = seeded["gestor_ids"][:STANDARD_GESTOR_LIMIT]
        dropped_ids = set(seeded["gestor_ids"][STANDARD_GESTOR_LIMIT:])

        with api_client() as client:
            listed = client.get(
                f"/api/admin/registrations/{seeded['seller_id']}/gestores",
                headers=admin_auth_headers(),
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(len(listed.json()), 12)
            self.assertTrue(all(item["is_active"] for item in listed.json()))

            updated = client.patch(
                f"/api/admin/registrations/{seeded['seller_id']}/subscription",
                headers=admin_auth_headers(),
                json={
                    "plan_tier": "standard",
                    "billing_period": "monthly",
                    "keep_gestor_ids": keep_ids,
                },
            )

        self.assertEqual(updated.status_code, 200, updated.text)
        body = updated.json()
        self.assertEqual(body["plan_tier"], "standard")
        self.assertEqual(body["billing_period"], "monthly")
        self.assertFalse(body["is_trial"])
        self.assertEqual(body["status"], "approved")

        seller, gestores = load_seller_and_gestores(seeded["seller_id"])
        self.assertEqual(seller["plan_tier"], "standard")
        self.assertFalse(seller.get("is_trial"))
        self.assertEqual(seller["billing_period"], "monthly")
        now = to_utc_naive(utc_now())
        self.assertGreaterEqual(seller["subscription_starts_at"], now - timedelta(minutes=2))
        self.assertLess(seller["subscription_ends_at"], now + timedelta(days=32))
        self.assertGreater(seller["subscription_ends_at"], now + timedelta(days=20))

        active = [doc for doc in gestores if doc.get("is_active", True)]
        inactive = [doc for doc in gestores if doc.get("is_active") is False]
        self.assertEqual({str(doc["_id"]) for doc in active}, set(keep_ids))
        self.assertEqual({str(doc["_id"]) for doc in inactive}, dropped_ids)
        self.assertEqual(set(seller.get("checkout_gestor_ids") or []), set(keep_ids))

    def test_admin_replace_rejects_keeping_more_gestores_than_the_plan_allows(self) -> None:
        seeded = seed_seller_with_gestores(plan_tier="premium", gestor_count=12)
        too_many = seeded["gestor_ids"][: STANDARD_GESTOR_LIMIT + 1]

        with api_client() as client:
            response = client.patch(
                f"/api/admin/registrations/{seeded['seller_id']}/subscription",
                headers=admin_auth_headers(),
                json={
                    "plan_tier": "standard",
                    "billing_period": "monthly",
                    "keep_gestor_ids": too_many,
                },
            )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json()["detail"],
            GESTOR_KEEP_LIMIT_MESSAGE.format(limit=STANDARD_GESTOR_LIMIT),
        )
        seller, gestores = load_seller_and_gestores(seeded["seller_id"])
        self.assertEqual(seller["plan_tier"], "premium")
        self.assertTrue(all(doc.get("is_active", True) for doc in gestores))

    def test_trial_store_replace_to_pro_does_not_deactivate_within_limit(self) -> None:
        seeded = seed_seller_with_gestores(plan_tier="standard", gestor_count=12, is_trial=True)

        with api_client() as client:
            response = client.patch(
                f"/api/admin/registrations/{seeded['seller_id']}/subscription",
                headers=admin_auth_headers(),
                json={
                    "plan_tier": "pro",
                    "billing_period": "quarterly",
                    "keep_gestor_ids": [],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["plan_tier"], "pro")
        self.assertFalse(body["is_trial"])
        seller, gestores = load_seller_and_gestores(seeded["seller_id"])
        self.assertFalse(seller.get("is_trial"))
        self.assertEqual(seller["billing_period"], "quarterly")
        self.assertEqual(len(gestores), 12)
        self.assertTrue(all(doc.get("is_active", True) for doc in gestores))
