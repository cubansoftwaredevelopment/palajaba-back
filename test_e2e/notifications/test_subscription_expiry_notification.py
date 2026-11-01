"""E2E coverage for idempotent subscription-expiry notifications."""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.database import get_notifications_collection, get_registrations_collection
from app.notifications.service import ensure_subscription_expiring_notifications
from app.subscriptions.service import NOTIFICATION_KIND_EXPIRING
from test_e2e.notifications.utils.fixtures import (
    cleanup_expiry_notification_seller,
    setup_expiry_notification_seller,
)
from test_e2e.utils.database import mongo_configured, run_db
from app.utils.datetime import to_utc_naive, utc_now


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SubscriptionExpiryNotificationE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.seller = setup_expiry_notification_seller()

    def tearDown(self) -> None:
        cleanup_expiry_notification_seller(self.seller["seller_id"])

    def test_concurrent_checks_create_one_trial_expiry_notification(self) -> None:
        async def exercise() -> tuple[int, int, list[dict]]:
            await get_registrations_collection().update_one(
                {"_id": ObjectId(self.seller["seller_id"])},
                {
                    "$set": {
                        "subscription_ends_at": to_utc_naive(utc_now() + timedelta(days=2))
                    }
                },
            )
            with (
                patch(
                    "app.notifications.service.publish_seller_notification",
                    new_callable=AsyncMock,
                ) as publish,
                patch(
                    "app.notifications.service.send_custom_sms",
                    new_callable=AsyncMock,
                ),
            ):
                results = await asyncio.gather(
                    ensure_subscription_expiring_notifications(),
                    ensure_subscription_expiring_notifications(),
                )
                notifications = await get_notifications_collection().find(
                    {
                        "seller_id": ObjectId(self.seller["seller_id"]),
                        "kind": NOTIFICATION_KIND_EXPIRING,
                    }
                ).to_list(length=10)
                return sum(results), publish.await_count, notifications

        created, published, notifications = run_db(exercise)

        self.assertEqual(len(notifications), 1)
        self.assertEqual(published, 1)
        self.assertEqual(created, 1)
        self.assertEqual(notifications[0]["title"], "Tu plan Prueba vence pronto")
        self.assertIn("plan Prueba", notifications[0]["content"])
