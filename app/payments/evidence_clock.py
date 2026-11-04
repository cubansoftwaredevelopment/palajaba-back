"""Pulso del servidor para que el plazo de la evidencia no cuente una caída."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.database import get_orders_collection, get_server_heartbeat_collection
from app.utils.datetime import to_utc_naive, utc_now

logger = logging.getLogger(__name__)

CLOCK_ID = "evidence_clock"
HEARTBEAT_INTERVAL = timedelta(seconds=5)
# Tres pulsos seguidos sin escribirse cuentan como caída, no como un tick lento.
DOWNTIME_THRESHOLD = HEARTBEAT_INTERVAL * 3

_heartbeat_task: asyncio.Task | None = None


async def record_server_heartbeat() -> timedelta:
    """Escribe la hora actual. Si el pulso anterior quedó viejo, alarga las evidencias pendientes."""
    now = to_utc_naive(utc_now())
    collection = get_server_heartbeat_collection()
    previous = await collection.find_one({"_id": CLOCK_ID})
    if previous is None or previous.get("beat_at") is None:
        await collection.update_one(
            {"_id": CLOCK_ID},
            {"$setOnInsert": {"beat_at": now}},
            upsert=True,
        )
        return timedelta(0)

    last_beat = to_utc_naive(previous["beat_at"])
    gap = now - last_beat
    claimed = await collection.update_one(
        {"_id": CLOCK_ID, "beat_at": previous["beat_at"]},
        {"$set": {"beat_at": now}},
    )
    if claimed.modified_count != 1 or gap <= DOWNTIME_THRESHOLD:
        return timedelta(0)

    downtime_ms = int(gap.total_seconds() * 1000)
    try:
        result = await get_orders_collection().update_many(
            {
                "payment_method": "qvapay",
                "qvapay.evidence.status": "pending",
                "qvapay.evidence.deadline": {"$type": "date"},
            },
            [
                {
                    "$set": {
                        "qvapay.evidence.deadline": {
                            "$add": ["$qvapay.evidence.deadline", downtime_ms]
                        }
                    }
                }
            ],
        )
    except Exception:
        await collection.update_one(
            {"_id": CLOCK_ID, "beat_at": now},
            {"$set": {"beat_at": previous["beat_at"]}},
        )
        raise
    logger.info(
        "El servidor estuvo detenido %s. Se alargó el plazo de %s evidencias pendientes.",
        gap,
        result.modified_count,
    )
    return gap


async def _heartbeat_loop() -> None:
    while True:
        try:
            await record_server_heartbeat()
        except Exception:
            logger.exception("No se pudo guardar el pulso del servidor")
        await asyncio.sleep(HEARTBEAT_INTERVAL.total_seconds())


def start_evidence_clock_task() -> asyncio.Task:
    global _heartbeat_task
    if _heartbeat_task is None or _heartbeat_task.done():
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    return _heartbeat_task


async def stop_evidence_clock_task() -> None:
    global _heartbeat_task
    if _heartbeat_task is None:
        return
    _heartbeat_task.cancel()
    try:
        await _heartbeat_task
    except asyncio.CancelledError:
        pass
    _heartbeat_task = None
