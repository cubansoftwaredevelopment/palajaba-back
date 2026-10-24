from typing import Literal

from pydantic import BaseModel, Field

BillingPeriod = Literal["monthly", "quarterly", "yearly"]
PlanTier = Literal["standard", "pro", "premium"]


class RegistrationSubscriptionReplace(BaseModel):
    plan_tier: PlanTier
    billing_period: BillingPeriod
    keep_gestor_ids: list[str] = Field(default_factory=list)
