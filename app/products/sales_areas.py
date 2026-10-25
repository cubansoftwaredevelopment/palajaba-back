"""Zonas de venta por producto: subconjunto de las zonas del perfil."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status


def area_key(area: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(area, dict):
        return ("", "")
    return (
        str(area.get("province_id") or "").strip(),
        str(area.get("municipality_id") or "").strip(),
    )


def _area_payload(area: dict[str, Any]) -> dict[str, str]:
    return {
        "province_id": str(area.get("province_id") or "").strip(),
        "province_name": str(area.get("province_name") or "").strip(),
        "municipality_id": str(area.get("municipality_id") or "").strip(),
        "municipality_name": str(area.get("municipality_name") or "").strip(),
    }


def seller_service_areas(seller: dict[str, Any] | None, *, offers_delivery: bool | None = None) -> list[dict[str, str]]:
    _ = offers_delivery
    if not seller:
        return []
    areas: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    business = seller.get("business_area")
    candidates = [business] if isinstance(business, dict) else []
    for item in seller.get("delivery_areas") or []:
        if isinstance(item, dict):
            candidates.append(item)
    for raw in candidates:
        payload = _area_payload(raw)
        key = (payload["province_id"], payload["municipality_id"])
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        areas.append(payload)
    return areas


def product_covers_municipality(
    product: dict[str, Any] | None,
    province_id: str,
    municipality_id: str,
) -> bool:
    if product is None:
        return False
    areas = product.get("sales_areas")
    if areas is None:
        return True
    if not isinstance(areas, list) or not areas:
        return False
    wanted = (str(province_id or "").strip(), str(municipality_id or "").strip())
    return any(area_key(item) == wanted for item in areas if isinstance(item, dict))


def sales_area_match_clause(province_id: str, municipality_id: str) -> dict[str, Any]:
    return {
        "$or": [
            {
                "sales_areas": {
                    "$elemMatch": {
                        "province_id": province_id,
                        "municipality_id": municipality_id,
                    }
                }
            },
            {"sales_areas": {"$exists": False}},
        ]
    }


def parse_sales_areas(
    raw: str | None,
    seller: dict[str, Any],
    *,
    offers_delivery: bool,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    allowed = {
        (item["province_id"], item["municipality_id"]): item
        for item in seller_service_areas(seller, offers_delivery=offers_delivery)
    }
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completa las zonas de tu perfil antes de publicar productos.",
        )

    if raw is None or not str(raw).strip():
        if fallback is not None:
            return parse_sales_areas(
                json.dumps(fallback),
                seller,
                offers_delivery=offers_delivery,
            )
        return list(allowed.values())

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las zonas de venta tienen un formato inválido.",
        ) from exc

    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las zonas de venta deben ser una lista.",
        )

    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in parsed:
        if isinstance(item, str) and ":" in item:
            province_id, municipality_id = item.split(":", 1)
            key = (province_id.strip(), municipality_id.strip())
        elif isinstance(item, dict):
            key = area_key(item)
        else:
            continue
        if key not in allowed or key in seen:
            continue
        seen.add(key)
        selected.append(allowed[key])

    if not selected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Elige al menos una zona de venta.",
        )
    return selected
