from __future__ import annotations

import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pymongo import ASCENDING

from app.database import get_discount_codes_collection
from app.schemas.discount_code import (
    DiscountCodeDeleteResult,
    DiscountCodePublic,
    DiscountCodeUpdate,
    ValidateDiscountCodePublic,
)
from app.services.plans import normalize_billing_period, normalize_plan_tier, plan_price_cup
from app.utils.datetime import to_utc_naive, utc_now

_CODE_PATTERN = re.compile(r"^[A-Z0-9_-]+$")


def normalize_discount_code(value: str) -> str:
    return value.strip().upper()


def apply_percent_discount(amount_cup: int, percent_off: int) -> int:
    if amount_cup <= 0:
        return 0
    if percent_off <= 0:
        return amount_cup
    if percent_off >= 100:
        return 0
    return max(0, int(amount_cup * (100 - percent_off) / 100))


def _validate_code_format(code: str) -> str:
    normalized = normalize_discount_code(code)
    if not _CODE_PATTERN.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El código solo puede contener letras, números, guiones y guiones bajos.",
        )
    return normalized


def _document_to_public(doc: dict[str, Any]) -> DiscountCodePublic:
    return DiscountCodePublic(
        id=str(doc["_id"]),
        code=doc["code"],
        percent_off=int(doc["percent_off"]),
        is_active=bool(doc.get("is_active", True)),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def ensure_discount_code_indexes() -> None:
    collection = get_discount_codes_collection()
    await collection.create_index([("code", ASCENDING)], unique=True)
    await collection.create_index([("is_active", ASCENDING), ("code", ASCENDING)])


async def has_active_discount_codes() -> bool:
    collection = get_discount_codes_collection()
    doc = await collection.find_one({"is_active": True}, {"_id": 1})
    return doc is not None


async def list_discount_codes() -> list[DiscountCodePublic]:
    collection = get_discount_codes_collection()
    docs = await collection.find({}).sort("code", ASCENDING).to_list(length=None)
    return [_document_to_public(doc) for doc in docs]


async def create_discount_code(*, code: str, percent_off: int, is_active: bool = True) -> DiscountCodePublic:
    normalized = _validate_code_format(code)
    collection = get_discount_codes_collection()
    now = to_utc_naive(utc_now())

    existing = await collection.find_one({"code": normalized})
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un código con ese nombre.",
        )

    doc = {
        "code": normalized,
        "percent_off": int(percent_off),
        "is_active": bool(is_active),
        "created_at": now,
        "updated_at": now,
    }
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _document_to_public(doc)


async def update_discount_code(discount_code_id: str, payload: DiscountCodeUpdate) -> DiscountCodePublic:
    collection = get_discount_codes_collection()
    doc = await _get_document_or_404(discount_code_id)
    updates: dict[str, Any] = {"updated_at": to_utc_naive(utc_now())}

    if payload.code is not None:
        normalized = _validate_code_format(payload.code)
        if normalized != doc["code"]:
            duplicate = await collection.find_one({"code": normalized, "_id": {"$ne": doc["_id"]}})
            if duplicate is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ya existe un código con ese nombre.",
                )
        updates["code"] = normalized

    if payload.percent_off is not None:
        updates["percent_off"] = int(payload.percent_off)

    if payload.is_active is not None:
        updates["is_active"] = bool(payload.is_active)

    if len(updates) == 1:
        return _document_to_public(doc)

    await collection.update_one({"_id": doc["_id"]}, {"$set": updates})
    updated = await collection.find_one({"_id": doc["_id"]})
    assert updated is not None
    return _document_to_public(updated)


async def delete_discount_code(discount_code_id: str) -> DiscountCodeDeleteResult:
    collection = get_discount_codes_collection()
    doc = await _get_document_or_404(discount_code_id)
    await collection.delete_one({"_id": doc["_id"]})
    return DiscountCodeDeleteResult(id=str(doc["_id"]), message="Código de descuento eliminado.")


async def _get_active_code_doc(code: str) -> dict[str, Any]:
    if not await has_active_discount_codes():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay códigos de descuento disponibles.",
        )

    normalized = _validate_code_format(code)
    collection = get_discount_codes_collection()
    doc = await collection.find_one({"code": normalized, "is_active": True})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de descuento no válido o inactivo.",
        )
    return doc


async def validate_discount_code(
    code: str,
    *,
    plan_tier: str,
    billing_period: str,
) -> ValidateDiscountCodePublic:
    doc = await _get_active_code_doc(code)
    tier = normalize_plan_tier(plan_tier)
    period = normalize_billing_period(billing_period)
    original_amount_cup = plan_price_cup(tier, period)
    percent_off = int(doc["percent_off"])
    discounted_amount_cup = apply_percent_discount(original_amount_cup, percent_off)

    return ValidateDiscountCodePublic(
        code=doc["code"],
        percent_off=percent_off,
        original_amount_cup=original_amount_cup,
        discounted_amount_cup=discounted_amount_cup,
    )


async def _get_document_or_404(discount_code_id: str) -> dict[str, Any]:
    try:
        object_id = ObjectId(discount_code_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de descuento no encontrado.",
        ) from exc

    doc = await get_discount_codes_collection().find_one({"_id": object_id})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de descuento no encontrado.",
        )
    return doc
