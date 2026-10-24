from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.subscriptions.service import (
    max_gestores_for_plan,
    normalize_billing_period,
    normalize_plan_tier,
)

GESTOR_NOT_OWNED_MESSAGE = "Algunos gestores no pertenecen a este negocio."
GESTOR_KEEP_LIMIT_MESSAGE = (
    "El plan permite hasta {limit} gestores activos. "
    "Elige cuáles se quedan y el resto se desactivan."
)


def subscription_period_end(start: datetime, billing_period: str) -> datetime:
    period = normalize_billing_period(billing_period)
    if period == "yearly":
        return start + timedelta(days=365)
    if period == "quarterly":
        return start + timedelta(days=90)
    return start + timedelta(days=30)


def build_subscription_replace_fields(
    now: datetime,
    *,
    plan_tier: str,
    billing_period: str,
) -> dict[str, Any]:
    """Campos que sustituyen la suscripción actual (empieza ahora, dura el periodo)."""
    tier = normalize_plan_tier(plan_tier)
    period = normalize_billing_period(billing_period)
    return {
        "plan_tier": tier,
        "billing_period": period,
        "is_trial": False,
        "status": "approved",
        "subscription_starts_at": now,
        "subscription_ends_at": subscription_period_end(now, period),
    }


def gestor_record_id(doc: dict[str, Any] | None) -> str:
    if not doc:
        return ""
    if doc.get("id") is not None:
        return str(doc["id"]).strip()
    if doc.get("_id") is not None:
        return str(doc["_id"]).strip()
    return ""


def gestor_record_is_active(doc: dict[str, Any] | None) -> bool:
    if not doc:
        return False
    return doc.get("is_active", True) is not False


def normalize_keep_gestor_ids(raw_ids: list[str] | None) -> list[str]:
    keep: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids or []:
        gestor_id = str(raw).strip()
        if not gestor_id or gestor_id in seen:
            continue
        seen.add(gestor_id)
        keep.append(gestor_id)
    return keep


def checkout_after_deactivate(
    checkout_gestor_ids: list[str] | None,
    deactivate_ids: list[str],
    *,
    include_store_phone: bool,
) -> tuple[list[str], bool]:
    dropped = set(deactivate_ids)
    remaining = [gid for gid in (checkout_gestor_ids or []) if gid not in dropped]
    include = bool(include_store_phone)
    if not remaining and not include:
        include = True
    return remaining, include


def resolve_gestor_keep_on_plan_change(
    *,
    plan_tier: str,
    gestores: list[dict[str, Any]],
    keep_gestor_ids: list[str] | None,
) -> dict[str, Any]:
    """Decide si hay que elegir gestores y cuáles desactivar al bajar de plan."""
    limit = max_gestores_for_plan(plan_tier)
    known_ids = {gestor_record_id(doc) for doc in gestores if gestor_record_id(doc)}
    active_ids = [
        gestor_record_id(doc)
        for doc in gestores
        if gestor_record_id(doc) and gestor_record_is_active(doc)
    ]
    needs_selection = limit is not None and len(active_ids) > limit
    result: dict[str, Any] = {
        "limit": limit,
        "needs_selection": needs_selection,
        "active_ids": active_ids,
        "keep_ids": list(active_ids),
        "deactivate_ids": [],
        "error": None,
    }
    if not needs_selection:
        return result

    keep_ids = normalize_keep_gestor_ids(keep_gestor_ids)
    for gestor_id in keep_ids:
        if gestor_id not in known_ids:
            result["keep_ids"] = keep_ids
            result["error"] = GESTOR_NOT_OWNED_MESSAGE
            return result

    if len(keep_ids) > limit:
        result["keep_ids"] = keep_ids
        result["error"] = GESTOR_KEEP_LIMIT_MESSAGE.format(limit=limit)
        return result

    keep_set = set(keep_ids)
    result["keep_ids"] = keep_ids
    result["deactivate_ids"] = [gestor_id for gestor_id in active_ids if gestor_id not in keep_set]
    return result
