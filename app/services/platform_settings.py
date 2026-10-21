from typing import Any

from fastapi import HTTPException, status

from app.constants import CURRENCY_CODES, DEFAULT_PLAN_PRICES
from app.database import get_platform_settings_collection
from app.schemas.platform_settings import (
    PlanPeriodPrices,
    PlanPriceConfig,
    PlanPricesSettings,
    PlatformSettingsPublic,
    PlatformSettingsUpdate,
    default_plan_prices,
)
from app.utils.datetime import to_utc_naive, utc_now

SETTINGS_ID = "global"


def _price_from_raw(raw: Any, fallback: dict[str, Any]) -> PlanPriceConfig:
    source = raw if isinstance(raw, dict) else {}
    try:
        amount = float(source.get("amount", fallback["amount"]))
    except (TypeError, ValueError):
        amount = float(fallback["amount"])
    if amount < 0:
        amount = float(fallback["amount"])
    currency = str(source.get("currency") or fallback["currency"]).strip().upper()
    if currency not in CURRENCY_CODES:
        currency = str(fallback["currency"])
    return PlanPriceConfig(amount=amount, currency=currency)


def _period_from_raw(raw: Any, fallback: dict[str, Any]) -> PlanPeriodPrices:
    source = raw if isinstance(raw, dict) else {}
    return PlanPeriodPrices(
        monthly=_price_from_raw(source.get("monthly"), fallback["monthly"]),
        yearly=_price_from_raw(source.get("yearly"), fallback["yearly"]),
    )


def parse_plan_prices(raw: Any) -> PlanPricesSettings:
    source = raw if isinstance(raw, dict) else {}
    return PlanPricesSettings(
        standard=_period_from_raw(source.get("standard"), DEFAULT_PLAN_PRICES["standard"]),
        premium=_period_from_raw(source.get("premium"), DEFAULT_PLAN_PRICES["premium"]),
    )


def _document_to_public(doc: dict[str, Any] | None) -> PlatformSettingsPublic:
    if not doc:
        return PlatformSettingsPublic()
    phone = doc.get("renewal_contact_phone")
    return PlatformSettingsPublic(
        renewal_contact_phone=phone if isinstance(phone, str) and phone else None,
        plan_prices=parse_plan_prices(doc.get("plan_prices")),
    )


async def ensure_platform_settings_indexes() -> None:
    collection = get_platform_settings_collection()
    await collection.create_index("_id")


async def get_platform_settings() -> PlatformSettingsPublic:
    collection = get_platform_settings_collection()
    doc = await collection.find_one({"_id": SETTINGS_ID})
    return _document_to_public(doc)


async def get_plan_prices() -> PlanPricesSettings:
    settings = await get_platform_settings()
    return settings.plan_prices or default_plan_prices()


async def get_renewal_contact_phone() -> str | None:
    settings = await get_platform_settings()
    return settings.renewal_contact_phone


async def update_platform_settings(payload: PlatformSettingsUpdate) -> PlatformSettingsPublic:
    now = to_utc_naive(utc_now())
    collection = get_platform_settings_collection()
    await collection.update_one(
        {"_id": SETTINGS_ID},
        {
            "$set": {
                "renewal_contact_phone": payload.renewal_contact_phone,
                "plan_prices": payload.plan_prices.model_dump(),
                "updated_at": now,
            },
            "$setOnInsert": {
                "_id": SETTINGS_ID,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return await get_platform_settings()


async def require_renewal_contact_phone() -> str:
    phone = await get_renewal_contact_phone()
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El administrador aún no configuró un teléfono para renovaciones.",
        )
    return phone
