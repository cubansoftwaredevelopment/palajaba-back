from typing import Any

from .schema import CustomerPublic


def customer_public(doc: dict[str, Any]) -> CustomerPublic:
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
