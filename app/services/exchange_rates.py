from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.database import get_exchange_rates_collection
from app.schemas.exchange_rates import ExchangeRatesPublic
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)

CACHE_DOCUMENT_ID = "eltoque_trmi"
SUPPORTED_CURRENCIES = ("CUP", "USD", "EUR", "MLC")
ELTOQUE_CURRENCY_MAP = {
    "USD": "USD",
    "ECU": "EUR",
    "MLC": "MLC",
}

FALLBACK_CUP_PER_UNIT: dict[str, float] = {
    "CUP": 1.0,
    "USD": 250.0,
    "EUR": 275.0,
    "MLC": 250.0,
}

_cup_per_unit_cache: dict[str, float] = dict(FALLBACK_CUP_PER_UNIT)
_cache_meta: dict[str, Any] = {
    "updated_at": None,
    "reference_date": None,
    "reference_time": None,
    "stale": True,
}
_refresh_lock = asyncio.Lock()
_refresh_task: asyncio.Task | None = None


def get_cup_per_unit() -> dict[str, float]:
    return dict(_cup_per_unit_cache)


def _format_reference_time(payload: dict[str, Any]) -> str | None:
    hour = payload.get("hour")
    minutes = payload.get("minutes")
    seconds = payload.get("seconds")
    if hour is None or minutes is None or seconds is None:
        return None
    return f"{int(hour):02d}:{int(minutes):02d}:{int(seconds):02d}"


def _normalize_eltoque_payload(payload: dict[str, Any]) -> tuple[dict[str, float], str | None, str | None]:
    tasas = payload.get("tasas")
    if not isinstance(tasas, dict):
        raise ValueError("Respuesta de elTOQUE sin campo tasas.")

    cup_per_unit: dict[str, float] = {"CUP": 1.0}
    for source_code, target_code in ELTOQUE_CURRENCY_MAP.items():
        raw_value = tasas.get(source_code)
        if raw_value is None:
            continue
        cup_per_unit[target_code] = float(raw_value)

    missing = [code for code in SUPPORTED_CURRENCIES if code not in cup_per_unit]
    if missing:
        raise ValueError(f"Faltan tasas requeridas de elTOQUE: {', '.join(missing)}")

    reference_date = str(payload.get("date") or "") or None
    reference_time = _format_reference_time(payload)
    return cup_per_unit, reference_date, reference_time


async def _fetch_eltoque_trmi(client: httpx.AsyncClient) -> dict[str, Any]:
    if not settings.eltoque_api_key.strip():
        raise RuntimeError("ELTOQUE_API_KEY no configurada.")

    today = utc_now().date().isoformat()
    response = await client.get(
        f"{settings.eltoque_api_base_url.rstrip('/')}/v1/trmi",
        params={"dateFrom": today, "dateTo": today},
        headers={
            "Authorization": f"Bearer {settings.eltoque_api_key.strip()}",
            "Accept": "application/json",
            "User-Agent": settings.eltoque_user_agent,
        },
        timeout=settings.eltoque_request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Respuesta de elTOQUE inválida.")
    return payload


async def _persist_rates(
    cup_per_unit: dict[str, float],
    *,
    reference_date: str | None,
    reference_time: str | None,
    stale: bool,
) -> None:
    global _cup_per_unit_cache, _cache_meta

    updated_at = to_utc_naive(utc_now())
    _cup_per_unit_cache = dict(cup_per_unit)
    _cache_meta = {
        "updated_at": updated_at,
        "reference_date": reference_date,
        "reference_time": reference_time,
        "stale": stale,
    }

    collection = get_exchange_rates_collection()
    await collection.update_one(
        {"_id": CACHE_DOCUMENT_ID},
        {
            "$set": {
                "cup_per_unit": cup_per_unit,
                "currencies": list(SUPPORTED_CURRENCIES),
                "source": "elTOQUE",
                "attribution": "Tasas de elTOQUE (TRMI)",
                "reference_date": reference_date,
                "reference_time": reference_time,
                "stale": stale,
                "updated_at": updated_at,
            }
        },
        upsert=True,
    )


async def _load_persisted_rates() -> bool:
    global _cup_per_unit_cache, _cache_meta

    doc = await get_exchange_rates_collection().find_one({"_id": CACHE_DOCUMENT_ID})
    if not doc:
        return False

    stored = doc.get("cup_per_unit")
    if not isinstance(stored, dict):
        return False

    cup_per_unit = {"CUP": 1.0}
    for code in SUPPORTED_CURRENCIES:
        if code == "CUP":
            continue
        value = stored.get(code)
        if value is None:
            return False
        cup_per_unit[code] = float(value)

    _cup_per_unit_cache = cup_per_unit
    _cache_meta = {
        "updated_at": doc.get("updated_at"),
        "reference_date": doc.get("reference_date"),
        "reference_time": doc.get("reference_time"),
        "stale": bool(doc.get("stale")),
    }
    return True


def _needs_refresh(updated_at: datetime | None) -> bool:
    if updated_at is None:
        return True
    normalized = to_utc_naive(updated_at) if updated_at.tzinfo else updated_at
    age_seconds = (to_utc_naive(utc_now()) - normalized).total_seconds()
    return age_seconds >= settings.exchange_rates_refresh_seconds


async def refresh_exchange_rates(*, force: bool = False) -> ExchangeRatesPublic:
    async with _refresh_lock:
        if not force and not _needs_refresh(_cache_meta.get("updated_at")):
            return build_exchange_rates_public()

        try:
            async with httpx.AsyncClient() as client:
                payload = await _fetch_eltoque_trmi(client)
            cup_per_unit, reference_date, reference_time = _normalize_eltoque_payload(payload)
            await _persist_rates(
                cup_per_unit,
                reference_date=reference_date,
                reference_time=reference_time,
                stale=False,
            )
            logger.info(
                "Tasas elTOQUE actualizadas (USD=%s, EUR=%s, MLC=%s)",
                cup_per_unit["USD"],
                cup_per_unit["EUR"],
                cup_per_unit["MLC"],
            )
        except Exception as exc:
            logger.warning("No se pudieron refrescar tasas de elTOQUE: %s", exc)
            if not await _load_persisted_rates():
                await _persist_rates(
                    FALLBACK_CUP_PER_UNIT,
                    reference_date=None,
                    reference_time=None,
                    stale=True,
                )

        return build_exchange_rates_public()


def build_exchange_rates_public() -> ExchangeRatesPublic:
    updated_at = _cache_meta.get("updated_at")
    return ExchangeRatesPublic(
        cup_per_unit=get_cup_per_unit(),
        currencies=list(SUPPORTED_CURRENCIES),
        updated_at=updated_at,
        source="elTOQUE",
        attribution="Tasas de elTOQUE (TRMI)",
        reference_date=_cache_meta.get("reference_date"),
        reference_time=_cache_meta.get("reference_time"),
        stale=bool(_cache_meta.get("stale")),
    )


async def ensure_exchange_rates_ready() -> None:
    loaded = await _load_persisted_rates()
    if not loaded or _needs_refresh(_cache_meta.get("updated_at")):
        await refresh_exchange_rates(force=True)


async def _periodic_refresh_loop() -> None:
    while True:
        await asyncio.sleep(settings.exchange_rates_refresh_seconds)
        try:
            await refresh_exchange_rates()
        except Exception as exc:
            logger.warning("Error en refresco periódico de tasas: %s", exc)


def start_exchange_rates_refresh_task() -> asyncio.Task:
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_periodic_refresh_loop())
    return _refresh_task


async def stop_exchange_rates_refresh_task() -> None:
    global _refresh_task
    if _refresh_task is None:
        return
    _refresh_task.cancel()
    try:
        await _refresh_task
    except asyncio.CancelledError:
        pass
    _refresh_task = None


async def ensure_exchange_rates_indexes() -> None:
    await get_exchange_rates_collection().create_index("updated_at")
