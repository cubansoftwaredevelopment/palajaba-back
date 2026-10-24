from typing import Literal

from app.utils.currency_conversion import convert_amount

PlanTier = Literal["standard", "pro", "premium"]
BillingPeriod = Literal["monthly", "quarterly", "yearly"]
BILLING_PERIODS: tuple[BillingPeriod, ...] = ("monthly", "quarterly", "yearly")

STANDARD_PLAN_TIER: PlanTier = "standard"
PRO_PLAN_TIER: PlanTier = "pro"
PREMIUM_PLAN_TIER: PlanTier = "premium"
PLAN_TIER_ORDER: tuple[PlanTier, ...] = (
    STANDARD_PLAN_TIER,
    PRO_PLAN_TIER,
    PREMIUM_PLAN_TIER,
)

STANDARD_GESTOR_LIMIT = 1
PRO_GESTOR_LIMIT = 3
PRO_RECOMMENDATION_MULTIPLIER = 2
PREMIUM_RECOMMENDATION_MULTIPLIER = 4

PLAN_DISPLAY_NAMES: dict[PlanTier, str] = {
    STANDARD_PLAN_TIER: "Básico",
    PRO_PLAN_TIER: "Pro",
    PREMIUM_PLAN_TIER: "Premium",
}

_PLAN_RANK: dict[PlanTier, int] = {
    STANDARD_PLAN_TIER: 0,
    PRO_PLAN_TIER: 1,
    PREMIUM_PLAN_TIER: 2,
}

STATISTICS_PLAN_REQUIRED_MESSAGE = (
    "Las estadísticas están disponibles en la prueba gratuita y en los planes Pro y Premium."
)
STORE_BANNERS_PLAN_REQUIRED_MESSAGE = (
    "Los banners de tienda están disponibles en la prueba gratuita y en los planes Pro y Premium."
)
CATALOG_THEME_PLAN_REQUIRED_MESSAGE = (
    "La personalización del catálogo está disponible en el plan Premium."
)


def normalize_plan_tier(value: str | None) -> PlanTier:
    if value == PRO_PLAN_TIER:
        return PRO_PLAN_TIER
    if value == PREMIUM_PLAN_TIER:
        return PREMIUM_PLAN_TIER
    return STANDARD_PLAN_TIER


def effective_plan_tier(doc: dict) -> PlanTier:
    return normalize_plan_tier(doc.get("plan_tier"))


def feature_plan_tier(doc: dict | None) -> PlanTier:
    """Plan cuyas prestaciones aplican: la prueba gratuita equivale a Pro."""
    payload = doc or {}
    tier = effective_plan_tier(payload)
    if tier in (PRO_PLAN_TIER, PREMIUM_PLAN_TIER):
        return tier
    if payload.get("is_trial"):
        return PRO_PLAN_TIER
    return STANDARD_PLAN_TIER


def plan_rank(plan_tier: str | None) -> int:
    return _PLAN_RANK[normalize_plan_tier(plan_tier)]


def plan_search_rank(doc: dict) -> int:
    """0 = Premium (primero), 1 = Pro, 2 = Básico."""
    return 2 - plan_rank(effective_plan_tier(doc))


def plan_display_name(plan_tier: str | None) -> str:
    return PLAN_DISPLAY_NAMES[normalize_plan_tier(plan_tier)]


def max_gestores_for_plan(plan_tier: str | None) -> int | None:
    """Tope de gestores por plan. None = ilimitado (Premium)."""
    tier = normalize_plan_tier(plan_tier)
    if tier == PREMIUM_PLAN_TIER:
        return None
    if tier == PRO_PLAN_TIER:
        return PRO_GESTOR_LIMIT
    return STANDARD_GESTOR_LIMIT


def max_gestores_for_seller(doc: dict | None) -> int | None:
    return max_gestores_for_plan(feature_plan_tier(doc))


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
    if value == "yearly":
        return "yearly"
    if value == "quarterly":
        return "quarterly"
    return "monthly"


async def plan_price_cup(plan_tier: str, billing_period: str) -> int:
    from app.services.platform_settings import get_plan_prices

    prices = await get_plan_prices()
    configured = prices.get_price(
        normalize_plan_tier(plan_tier),
        normalize_billing_period(billing_period),
    )
    return int(convert_amount(configured.amount, configured.currency, "CUP"))


def seller_has_statistics(doc: dict) -> bool:
    return plan_rank(feature_plan_tier(doc)) >= 1


def seller_has_recommendation_boost(doc: dict) -> bool:
    return seller_has_statistics(doc)


def seller_has_store_banners(doc: dict) -> bool:
    return plan_rank(feature_plan_tier(doc)) >= 1


def seller_has_full_store_customization(doc: dict) -> bool:
    return feature_plan_tier(doc) == PREMIUM_PLAN_TIER


def recommendation_multiplier(doc: dict) -> int:
    tier = feature_plan_tier(doc)
    if tier == PREMIUM_PLAN_TIER:
        return PREMIUM_RECOMMENDATION_MULTIPLIER
    if tier == PRO_PLAN_TIER:
        return PRO_RECOMMENDATION_MULTIPLIER
    return 1
