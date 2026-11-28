from datetime import datetime
from typing import Any

from app.utils.datetime import to_utc_naive

from .schema import CustomerPublic


def customer_section_dates(doc: dict[str, Any]) -> dict[str, datetime]:
    raw = doc.get("section_updated_at") or {}
    created = doc.get("created_at") if isinstance(doc.get("created_at"), datetime) else None
    dates: dict[str, datetime] = {}
    for name in ("perfil", "direcciones", "favoritos"):
        value = raw.get(name) if isinstance(raw.get(name), datetime) else created
        if isinstance(value, datetime):
            dates[name] = to_utc_naive(value)
    for name in ("pedidos", "avisos"):
        value = raw.get(name)
        if isinstance(value, datetime):
            dates[name] = to_utc_naive(value)
    return dates


def customer_public(doc: dict[str, Any]) -> CustomerPublic:
    updated = doc.get("updated_at") if isinstance(doc.get("updated_at"), datetime) else doc.get("created_at")
    return CustomerPublic(
        id=str(doc["_id"]),
        full_name=doc["full_name"],
        email=doc["email"],
        phone=f"+53{doc['phone']}",
        identity_card=doc["identity_card"],
        profile_photo_url=doc.get("profile_photo_url"),
        addresses=doc.get("addresses") or [],
        favorite_product_ids=doc.get("favorite_product_ids") or [],
        favorites=doc.get("favorites") or [],
        qvapay_username=doc.get("qvapay_username"),
        qvapay_verified=bool(doc.get("qvapay_username") and doc.get("qvapay_verified_at")),
        qvapay_prompt_dismissed=bool(doc.get("qvapay_prompt_dismissed")),
        purchase_revoked=bool(doc.get("purchase_revoked")),
        updated_at=to_utc_naive(updated) if isinstance(updated, datetime) else None,
        section_updated_at=customer_section_dates(doc),
    )


def mask_customer_phone(phone: str) -> str:
    digits = "".join(character for character in str(phone or "") if character.isdigit())[-8:]
    return f"{digits[:2]}****{digits[-2:]}" if len(digits) == 8 else "***"


def store_customer_order_location(order: dict[str, Any]) -> str:
    zone = order.get("buyer_zone") or {}
    province_name = str(zone.get("province_name") or "").strip()
    municipality_name = str(zone.get("municipality_name") or "").strip()
    if not province_name and not municipality_name:
        return ""
    return f"{zone.get('province_id') or province_name}|{zone.get('municipality_id') or municipality_name}"
