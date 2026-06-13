from typing import Literal

from app.constants import PLAN_PRICES_USD
from app.utils.currency_conversion import convert_amount

PlanTier = Literal["standard", "premium"]
BillingPeriod = Literal["monthly", "yearly"]

STANDARD_PLAN_TIER: PlanTier = "standard"
PREMIUM_PLAN_TIER: PlanTier = "premium"
PREMIUM_RECOMMENDATION_MULTIPLIER = 2


def normalize_plan_tier(value: str | None) -> PlanTier:
    if value == PREMIUM_PLAN_TIER:
        return PREMIUM_PLAN_TIER
    return STANDARD_PLAN_TIER


def normalize_billing_period(value: str | None) -> BillingPeriod:
    return "yearly" if value == "yearly" else "monthly"


def plan_price_usd(plan_tier: str, billing_period: str) -> int:
    tier = normalize_plan_tier(plan_tier)
    period = "yearly" if billing_period == "yearly" else "monthly"
    return PLAN_PRICES_USD[tier][period]


def plan_price_cup(plan_tier: str, billing_period: str) -> int:
    usd_amount = plan_price_usd(plan_tier, billing_period)
    return int(convert_amount(usd_amount, "USD", "CUP"))


def seller_has_statistics(doc: dict) -> bool:
    return normalize_plan_tier(doc.get("plan_tier")) == PREMIUM_PLAN_TIER


def seller_has_recommendation_boost(doc: dict) -> bool:
    return seller_has_statistics(doc)


def recommendation_multiplier(doc: dict) -> int:
    if seller_has_recommendation_boost(doc):
        return PREMIUM_RECOMMENDATION_MULTIPLIER
    return 1
