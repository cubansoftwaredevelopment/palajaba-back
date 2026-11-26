"""Funciones que se compran para armar un plan de tienda."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from app.utils.datetime import to_utc_naive, utc_now

PLUGIN_REQUIRED_MESSAGE = "Esta función no está en tu plan."
MENSAJEROS_QUOTA_MESSAGE = "Agotado el número de mensajeros de su plan."
DISCOUNTS_QUOTA_MESSAGE = "Agotado el número de descuento a productos."

BOOLEAN_PLUGINS = (
    "whatsapp_orders",
    "catalog_palette",
    "customers",
    "customer_notices",
    "automatic_orders",
    "manual_orders",
    "statistics",
)
QUANTITY_PLUGINS = (
    "gestores",
    "recommendation_boost",
    "mensajeros",
    "discounts",
    "banners",
)
PLUGIN_IDS = BOOLEAN_PLUGINS + QUANTITY_PLUGINS

PLUGIN_LABELS = {
    "whatsapp_orders": "Pedidos a WhatsApp",
    "gestores": "Gestores",
    "catalog_palette": "Paleta de colores del catálogo",
    "recommendation_boost": "Boost de recomendación",
    "mensajeros": "Mensajeros",
    "customers": "Clientes",
    "customer_notices": "Avisos a clientes",
    "automatic_orders": "Pedidos automáticos",
    "manual_orders": "Pedidos manuales",
    "statistics": "Estadísticas",
    "discounts": "Descuentos",
    "banners": "Banners",
}

DEFAULT_PLUGIN_PRICES_USD = {
    "whatsapp_orders": 1,
    "gestores": 1,
    "catalog_palette": 2,
    "recommendation_boost": 1,
    "mensajeros": 1,
    "customers": 1,
    "customer_notices": 1,
    "automatic_orders": 1,
    "manual_orders": 1,
    "statistics": 2,
    "discounts": 1,
    "banners": 1,
}


def period_factor(period: str | None) -> int:
    if period == "yearly":
        return 12
    if period == "quarterly":
        return 3
    return 1


def is_custom_plan(doc: dict | None) -> bool:
    return (doc or {}).get("plan_tier") == "custom"


def parse_plugin_prices(raw: Any) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    prices: dict[str, float] = {}
    for key in PLUGIN_IDS:
        try:
            amount = float(source.get(key, DEFAULT_PLUGIN_PRICES_USD[key]))
        except (TypeError, ValueError):
            amount = float(DEFAULT_PLUGIN_PRICES_USD[key])
        prices[key] = max(0.0, amount)
    return prices


def normalize_plugin_selection(raw: Any, *, customers_included: bool = False) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    selection: dict[str, int] = {}
    for key in PLUGIN_IDS:
        try:
            qty = int(source.get(key) or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty < 0:
            qty = 0
        if key in BOOLEAN_PLUGINS:
            qty = 1 if qty else 0
        if qty:
            selection[key] = qty
    if selection.get("customer_notices") and not selection.get("customers") and not customers_included:
        selection.pop("customer_notices", None)
    selection.pop("automatic_orders", None)
    return selection


def plugins_total_usd(prices: dict[str, float], selection: dict[str, int], period: str | None) -> float:
    factor = period_factor(period)
    total = 0.0
    for key, qty in selection.items():
        total += float(prices.get(key) or 0) * qty * factor
    return round(total, 2)


def addon_quantity(doc: dict | None, key: str) -> int:
    return _addon_quantity(doc or {}, key)


def _addon_quantity(doc: dict, key: str) -> int:
    expires = doc.get("plugin_addons_expires_at")
    if isinstance(expires, datetime) and to_utc_naive(expires) <= to_utc_naive(utc_now()):
        return 0
    try:
        qty = int((doc.get("plugin_addons") or {}).get(key) or 0)
    except (TypeError, ValueError):
        qty = 0
    return max(0, qty)


def selected_quantity(doc: dict | None, key: str) -> int:
    """Cantidad contratada. En un plan fijo, 0 si no compró el extra."""
    payload = doc or {}
    base = 0
    if is_custom_plan(payload):
        try:
            base = int((payload.get("plan_plugins") or {}).get(key) or 0)
        except (TypeError, ValueError):
            base = 0
    return max(0, base) + _addon_quantity(payload, key)


def require_plugin(doc: dict | None, key: str) -> None:
    if is_custom_plan(doc):
        if selected_quantity(doc, key) <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PLUGIN_REQUIRED_MESSAGE)
        return
    if _addon_quantity(doc or {}, key) <= 0 and not _legacy_enabled(doc, key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PLUGIN_REQUIRED_MESSAGE)


def _legacy_enabled(doc: dict | None, key: str) -> bool:
    """Prestación incluida hoy en Básico, Pro, Premium o prueba, sin mirar plugins."""
    from app.subscriptions.service import PREMIUM_PLAN_TIER, feature_plan_tier, plan_rank

    payload = doc or {}
    if payload.get("plan_tier") == "custom":
        return False
    tier = feature_plan_tier(payload)
    paid_plus = plan_rank(tier) >= 1
    if key in {"whatsapp_orders", "customers", "customer_notices", "automatic_orders", "manual_orders", "gestores"}:
        return True
    if key == "catalog_palette":
        return tier == PREMIUM_PLAN_TIER
    if key in {"mensajeros", "statistics", "discounts", "banners", "recommendation_boost"}:
        return paid_plus
    return False


def seller_has_plugin(doc: dict | None, key: str) -> bool:
    return feature_on(doc, key, legacy=_legacy_enabled(doc, key))


def feature_on(doc: dict | None, key: str, *, legacy: bool) -> bool:
    payload = doc or {}
    if is_custom_plan(payload):
        return selected_quantity(payload, key) > 0
    return bool(legacy) or _addon_quantity(payload, key) > 0


def quantity_cap(doc: dict | None, key: str, *, legacy_limit: int | None, legacy_included: bool) -> int | None:
    """None = ilimitado. Un entero es el máximo, incluido 0."""
    payload = doc or {}
    addon = _addon_quantity(payload, key)
    if is_custom_plan(payload):
        try:
            base = int((payload.get("plan_plugins") or {}).get(key) or 0)
        except (TypeError, ValueError):
            base = 0
        return max(0, base) + addon
    if legacy_limit is None and legacy_included:
        return None
    if legacy_included and legacy_limit is None:
        return None
    base = legacy_limit if legacy_limit is not None else (10**9 if legacy_included else 0)
    if legacy_included and legacy_limit is None:
        return None
    return base + addon


def plugin_access_map(doc: dict | None, *, gestores_cap: int | None) -> dict[str, int | None]:
    payload = doc or {}
    access: dict[str, int | None] = {}
    for key in PLUGIN_IDS:
        if key == "gestores":
            access[key] = gestores_cap
            continue
        if is_custom_plan(payload):
            access[key] = selected_quantity(payload, key)
            continue
        if _legacy_enabled(payload, key):
            access[key] = None
            continue
        extra = _addon_quantity(payload, key)
        access[key] = extra if key in QUANTITY_PLUGINS else (1 if extra else 0)
    return access


def require_quantity_slot(doc: dict | None, key: str, current: int, *, legacy_limit: int | None, legacy_included: bool) -> None:
    cap = quantity_cap(doc, key, legacy_limit=legacy_limit, legacy_included=legacy_included)
    if cap is None:
        return
    if current >= cap:
        detail = {
            "mensajeros": MENSAJEROS_QUOTA_MESSAGE,
            "discounts": DISCOUNTS_QUOTA_MESSAGE,
        }.get(key, PLUGIN_REQUIRED_MESSAGE) if cap > 0 else PLUGIN_REQUIRED_MESSAGE
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
