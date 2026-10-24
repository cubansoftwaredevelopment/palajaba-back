from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.constants import CURRENCY_CODES, DEFAULT_ADVERTISING_PRICES, DEFAULT_PLAN_PRICES
from app.database import get_platform_settings_collection
from app.schemas.platform_settings import (
    AdvertisingPlanPrice,
    AdvertisingPricesSettings,
    PlanPeriodPrices,
    PlanPriceConfig,
    PlanPricesSettings,
    PlatformAdminContact,
    PlatformSettingsPublic,
    PlatformSettingsUpdate,
    default_advertising_prices,
    default_plan_prices,
    normalize_admin_email,
)
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.phone import normalize_admin_phone

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
        quarterly=_price_from_raw(source.get("quarterly"), fallback["quarterly"]),
        yearly=_price_from_raw(source.get("yearly"), fallback["yearly"]),
    )


def parse_plan_prices(raw: Any) -> PlanPricesSettings:
    source = raw if isinstance(raw, dict) else {}
    return PlanPricesSettings(
        standard=_period_from_raw(source.get("standard"), DEFAULT_PLAN_PRICES["standard"]),
        pro=_period_from_raw(source.get("pro"), DEFAULT_PLAN_PRICES["pro"]),
        premium=_period_from_raw(source.get("premium"), DEFAULT_PLAN_PRICES["premium"]),
    )


def _advertising_amount(raw: Any, fallback: float) -> float:
    source = raw if isinstance(raw, dict) else {}
    try:
        amount = float(source.get("amount", fallback) if isinstance(raw, dict) else raw)
    except (TypeError, ValueError):
        amount = float(fallback)
    if amount < 0:
        return float(fallback)
    return amount


def parse_advertising_prices(raw: Any) -> AdvertisingPricesSettings:
    source = raw if isinstance(raw, dict) else {}
    return AdvertisingPricesSettings(
        ads_10=AdvertisingPlanPrice(
            amount=_advertising_amount(source.get("ads-10"), DEFAULT_ADVERTISING_PRICES["ads-10"])
        ),
        ads_20=AdvertisingPlanPrice(
            amount=_advertising_amount(source.get("ads-20"), DEFAULT_ADVERTISING_PRICES["ads-20"])
        ),
        ads_30=AdvertisingPlanPrice(
            amount=_advertising_amount(source.get("ads-30"), DEFAULT_ADVERTISING_PRICES["ads-30"])
        ),
    )


def _admin_email_from_raw(raw: Any) -> str | None:
    try:
        return normalize_admin_email(str(raw) if raw is not None else None)
    except ValueError:
        email = str(raw or "").strip().lower()
        return email or None


def _admin_phone_from_raw(raw: Any) -> str | None:
    try:
        return normalize_admin_phone(str(raw) if raw is not None else None)
    except ValueError:
        return None


def parse_admins(raw: Any, legacy_email: Any = None, legacy_phone: Any = None) -> list[PlatformAdminContact]:
    contacts: list[PlatformAdminContact] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                contacts.append(PlatformAdminContact.model_validate(item))
            except (TypeError, ValueError, ValidationError):
                continue
    if contacts:
        return contacts
    email = _admin_email_from_raw(legacy_email)
    phone = _admin_phone_from_raw(legacy_phone)
    if not email or not phone:
        return []
    try:
        return [PlatformAdminContact(email=email, phone=phone)]
    except (TypeError, ValueError, ValidationError):
        return []


def _document_to_public(doc: dict[str, Any] | None) -> PlatformSettingsPublic:
    if not doc:
        return PlatformSettingsPublic()
    phone = doc.get("renewal_contact_phone")
    admins = parse_admins(doc.get("admins"), doc.get("admin_email"), doc.get("admin_phone"))
    first = admins[0] if admins else None
    return PlatformSettingsPublic(
        renewal_contact_phone=phone if isinstance(phone, str) and phone else None,
        plan_prices=parse_plan_prices(doc.get("plan_prices")),
        advertising_prices=parse_advertising_prices(doc.get("advertising_prices")),
        admins=admins,
        admin_email=first.email if first else None,
        admin_phone=first.phone if first else None,
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


async def get_advertising_prices() -> AdvertisingPricesSettings:
    settings = await get_platform_settings()
    return settings.advertising_prices or default_advertising_prices()


async def get_renewal_contact_phone() -> str | None:
    settings = await get_platform_settings()
    return settings.renewal_contact_phone


async def update_platform_settings(payload: PlatformSettingsUpdate) -> PlatformSettingsPublic:
    now = to_utc_naive(utc_now())
    updates: dict[str, Any] = {"updated_at": now}
    if payload.renewal_contact_phone is not None:
        updates["renewal_contact_phone"] = payload.renewal_contact_phone
    if payload.plan_prices is not None:
        updates["plan_prices"] = payload.plan_prices.model_dump()
    if payload.advertising_prices is not None:
        updates["advertising_prices"] = payload.advertising_prices.model_dump(by_alias=True)
    if payload.admins is not None:
        dumped = [admin.model_dump() for admin in payload.admins]
        updates["admins"] = dumped
        first = dumped[0] if dumped else {}
        updates["admin_email"] = first.get("email")
        updates["admin_phone"] = first.get("phone")
    else:
        if payload.admin_email is not None:
            updates["admin_email"] = payload.admin_email
        if payload.admin_phone is not None:
            updates["admin_phone"] = payload.admin_phone

    collection = get_platform_settings_collection()
    await collection.update_one(
        {"_id": SETTINGS_ID},
        {
            "$set": updates,
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
