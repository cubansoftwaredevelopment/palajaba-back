from typing import Literal

from app.utils.currency_conversion import convert_amount

PlanTier = Literal["standard", "premium"]
BillingPeriod = Literal["monthly", "yearly"]

STANDARD_PLAN_TIER: PlanTier = "standard"
PREMIUM_PLAN_TIER: PlanTier = "premium"
PREMIUM_RECOMMENDATION_MULTIPLIER = 2
STANDARD_GESTOR_LIMIT = 3


def normalize_plan_tier(value: str | None) -> PlanTier:
    if value == PREMIUM_PLAN_TIER:
        return PREMIUM_PLAN_TIER
    return STANDARD_PLAN_TIER


def effective_plan_tier(doc: dict) -> PlanTier:
    return normalize_plan_tier(doc.get("plan_tier"))


def max_gestores_for_plan(plan_tier: str | None) -> int | None:
    """Tope de gestores por plan. None = ilimitado (Premium)."""
    if normalize_plan_tier(plan_tier) == PREMIUM_PLAN_TIER:
        return None
    return STANDARD_GESTOR_LIMIT


def seller_can_add_gestor(plan_tier: str | None, current_count: int) -> bool:
    limit = max_gestores_for_plan(plan_tier)
    if limit is None:
        return True
    try:
        count = int(current_count)
    except (TypeError, ValueError):
        count = 0
    return count < limit


def normalize_billing_period(value: str | None) -> BillingPeriod:
    return "yearly" if value == "yearly" else "monthly"


async def plan_price_cup(plan_tier: str, billing_period: str) -> int:
    from app.services.platform_settings import get_plan_prices

    prices = await get_plan_prices()
    configured = prices.get_price(
        normalize_plan_tier(plan_tier),
        normalize_billing_period(billing_period),
    )
    return int(convert_amount(configured.amount, configured.currency, "CUP"))


def seller_has_statistics(doc: dict) -> bool:
    return effective_plan_tier(doc) == PREMIUM_PLAN_TIER


def seller_has_recommendation_boost(doc: dict) -> bool:
    return seller_has_statistics(doc)


def recommendation_multiplier(doc: dict) -> int:
    if seller_has_recommendation_boost(doc):
        return PREMIUM_RECOMMENDATION_MULTIPLIER
    return 1
