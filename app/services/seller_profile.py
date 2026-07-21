from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.database import get_registrations_collection
from app.services.media_storage import read_image_upload, remove_image, store_image
from app.schemas.auth import SellerPublic
from app.schemas.seller_profile import (
    BusinessArea,
    BusinessLocation,
    CategoryPublic,
    SellerPhoneUpdate,
    SellerProfileUpdate,
    SellerStoreNameUpdate,
)
from app.services.catalog_theme import normalize_catalog_theme
from app.services.categories import categories_for_profile, validate_category_ids
from app.services.cuba_locations import validate_business_area
from app.services.gestores import parse_gestor_catalog_access
from app.services.plans import (
    normalize_plan_tier,
    seller_has_recommendation_boost,
    seller_has_statistics,
)
from app.services.subscriptions import (
    is_publicly_visible,
    is_subscription_active,
    subscription_days_remaining,
    subscription_hours_remaining,
)
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.phone import phone_display
from app.utils.store_slug import store_name_to_slug

UPLOADS_DIR = Path(__file__).resolve().parents[2] / "uploads" / "profiles"


def _area_key(area: dict[str, str]) -> str:
    return f"{area['province_id']}:{area['municipality_id']}"


def _parse_business_area(raw: Any) -> BusinessArea | None:
    if not isinstance(raw, dict):
        return None
    required = ("province_id", "province_name", "municipality_id", "municipality_name")
    if not all(raw.get(key) for key in required):
        return None
    return BusinessArea(
        province_id=raw["province_id"],
        province_name=raw["province_name"],
        municipality_id=raw["municipality_id"],
        municipality_name=raw["municipality_name"],
    )


def _parse_delivery_areas(raw: Any) -> list[BusinessArea]:
    if not isinstance(raw, list):
        return []
    areas: list[BusinessArea] = []
    for item in raw:
        parsed = _parse_business_area(item)
        if parsed is not None:
            areas.append(parsed)
    return areas


def _normalize_business_area(area: BusinessArea) -> dict[str, str]:
    return validate_business_area(
        area.province_id,
        area.province_name,
        area.municipality_id,
        area.municipality_name,
    )


def _normalize_delivery_areas(
    business_area: dict[str, str],
    delivery_areas: list[BusinessArea],
) -> list[dict[str, str]]:
    seen = {_area_key(business_area)}
    normalized: list[dict[str, str]] = []

    for area in delivery_areas:
        validated = _normalize_business_area(area)
        key = _area_key(validated)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(validated)

    return normalized


def is_profile_complete(doc: dict[str, Any]) -> bool:
    return bool(
        doc.get("profile_photo_url")
        and doc.get("category_ids")
        and doc.get("offers_delivery") is not None
        and _parse_business_area(doc.get("business_area")) is not None
    )


def document_to_seller(doc: dict[str, Any]) -> SellerPublic:
    location = doc.get("business_location")
    business_location = None
    if isinstance(location, dict) and location.get("lat") is not None:
        business_location = BusinessLocation(
            lat=location["lat"],
            lng=location["lng"],
            label=location.get("label"),
        )

    completed = is_profile_complete(doc)
    active = is_subscription_active(doc)
    days_remaining = subscription_days_remaining(doc)
    hours_remaining = subscription_hours_remaining(doc)

    return SellerPublic(
        id=str(doc["_id"]),
        store_name=doc["store_name"],
        phone=phone_display(doc["phone"]),
        billing_period=doc["billing_period"],
        plan_tier=normalize_plan_tier(doc.get("plan_tier")),
        has_statistics=seller_has_statistics(doc),
        has_recommendation_boost=seller_has_recommendation_boost(doc),
        subscription_ends_at=doc.get("subscription_ends_at"),
        profile_photo_url=doc.get("profile_photo_url"),
        business_location=business_location,
        business_area=_parse_business_area(doc.get("business_area")),
        delivery_areas=_parse_delivery_areas(doc.get("delivery_areas")),
        biography=doc.get("biography"),
        social_instagram=doc.get("social_instagram"),
        social_facebook=doc.get("social_facebook"),
        category_ids=doc.get("category_ids") or [],
        offers_delivery=doc.get("offers_delivery"),
        gestores_enabled=bool(doc.get("gestores_enabled")),
        profile_completed=completed,
        profile_completed_at=doc.get("profile_completed_at"),
        subscription_active=active,
        subscription_days_remaining=days_remaining,
        subscription_hours_remaining=hours_remaining,
        catalog_theme=normalize_catalog_theme(doc.get("catalog_theme")),
        gestor_catalog_access=parse_gestor_catalog_access(doc.get("gestor_catalog_access")),
    )


async def _get_seller_doc(seller_id: str) -> dict[str, Any]:
    from bson import ObjectId

    collection = get_registrations_collection()
    try:
        object_id = ObjectId(seller_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        ) from exc

    doc = await collection.find_one({"_id": object_id})
    if doc is None or not is_publicly_visible(doc):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )
    return doc


async def get_seller_public(seller_id: str) -> SellerPublic:
    doc = await _get_seller_doc(seller_id)
    return document_to_seller(doc)


async def get_seller_business_categories(seller_id: str) -> list[CategoryPublic]:
    doc = await _get_seller_doc(seller_id)
    return categories_for_profile(doc.get("category_ids") or [])


async def update_seller_profile(
    seller_id: str,
    payload: SellerProfileUpdate,
) -> SellerPublic:
    doc = await _get_seller_doc(seller_id)
    await validate_category_ids(payload.category_ids)

    if not doc.get("profile_photo_url"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sube una foto de perfil antes de guardar.",
        )

    business_area = _normalize_business_area(payload.business_area)
    delivery_areas = (
        _normalize_delivery_areas(business_area, payload.delivery_areas)
        if payload.offers_delivery
        else []
    )

    now = to_utc_naive(utc_now())
    update_fields: dict[str, Any] = {
        "biography": payload.biography,
        "social_instagram": payload.social_instagram,
        "social_facebook": payload.social_facebook,
        "category_ids": payload.category_ids,
        "offers_delivery": payload.offers_delivery,
        "gestores_enabled": bool(payload.gestores_enabled),
        "business_area": business_area,
        "delivery_areas": delivery_areas,
        "updated_at": now,
    }

    if payload.clear_business_location:
        update_fields["business_location"] = None
    elif payload.business_location is not None:
        update_fields["business_location"] = payload.business_location.model_dump()

    was_complete = is_profile_complete(doc)
    will_be_complete = bool(
        doc.get("profile_photo_url")
        and payload.category_ids
        and payload.offers_delivery is not None
        and business_area
    )

    if will_be_complete and not was_complete:
        update_fields["profile_completed_at"] = now
    elif not will_be_complete:
        update_fields["profile_completed_at"] = None

    collection = get_registrations_collection()
    await collection.update_one({"_id": doc["_id"]}, {"$set": update_fields})

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_seller(updated)


async def update_seller_store_name(
    seller_id: str,
    payload: SellerStoreNameUpdate,
) -> SellerPublic:
    doc = await _get_seller_doc(seller_id)
    new_store_name = payload.store_name
    current_store_name = doc.get("store_name") or ""

    if current_store_name.lower() == new_store_name.lower():
        return document_to_seller(doc)

    collection = get_registrations_collection()
    existing = await collection.find_one(
        {
            "store_name": {"$regex": f"^{new_store_name}$", "$options": "i"},
            "_id": {"$ne": doc["_id"]},
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese nombre ya está ocupado.",
        )

    now = to_utc_naive(utc_now())
    await collection.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "store_name": new_store_name,
                "store_slug": store_name_to_slug(new_store_name),
                "updated_at": now,
            }
        },
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_seller(updated)


async def update_seller_phone(seller_id: str, payload: SellerPhoneUpdate) -> SellerPublic:
    doc = await _get_seller_doc(seller_id)
    new_phone = payload.phone

    if new_phone == doc.get("phone"):
        return document_to_seller(doc)

    collection = get_registrations_collection()
    existing = await collection.find_one({"phone": new_phone, "_id": {"$ne": doc["_id"]}})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese número ya está registrado en otra tienda.",
        )

    now = to_utc_naive(utc_now())
    await collection.update_one(
        {"_id": doc["_id"]},
        {"$set": {"phone": new_phone, "updated_at": now}},
    )

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_seller(updated)


async def save_profile_photo(seller_id: str, file: UploadFile) -> SellerPublic:
    doc = await _get_seller_doc(seller_id)

    content, content_type = await read_image_upload(file)
    stored_image = await store_image(
        content,
        content_type,
        scope="profiles",
        owner_id=seller_id,
    )
    photo_url = stored_image.url

    old_url = doc.get("profile_photo_url")
    now = to_utc_naive(utc_now())

    collection = get_registrations_collection()
    await collection.update_one(
        {"_id": doc["_id"]},
        {"$set": {"profile_photo_url": photo_url, "updated_at": now}},
    )

    if old_url and old_url != photo_url:
        await remove_image(old_url)

    updated = await collection.find_one({"_id": doc["_id"]})
    return document_to_seller(updated)


def ensure_uploads_dir() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
