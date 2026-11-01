"""Datos de prueba y ciclo de vida para notificaciones."""

from __future__ import annotations

from bson import ObjectId

from app.database import get_notifications_collection
from app.subscriptions.service import PREMIUM_PLAN_TIER, PRO_PLAN_TIER, STANDARD_PLAN_TIER
from test_e2e.subscriptions.utils.fixtures import cleanup_db as cleanup_subscription_sellers
from test_e2e.subscriptions.utils.fixtures import seed_seller
from test_e2e.utils.database import run_db


def audience_sellers() -> list[dict]:
    return [
        {"_id": "p-m", "plan_tier": PREMIUM_PLAN_TIER, "billing_period": "monthly"},
        {"_id": "p-y", "plan_tier": PREMIUM_PLAN_TIER, "billing_period": "yearly"},
        {"_id": "pro-m", "plan_tier": PRO_PLAN_TIER, "billing_period": "monthly"},
        {"_id": "std-m", "plan_tier": STANDARD_PLAN_TIER, "billing_period": "monthly"},
    ]


def setup_expiry_notification_seller() -> dict[str, str]:
    cleanup_subscription_sellers()
    return seed_seller(plan_tier="standard", is_trial=True, subscription_days=20)


def cleanup_expiry_notification_seller(seller_id: str) -> None:
    seller_oid = ObjectId(seller_id)

    async def cleanup_notifications() -> None:
        await get_notifications_collection().delete_many({"seller_id": seller_oid})

    run_db(cleanup_notifications)
    cleanup_subscription_sellers()
