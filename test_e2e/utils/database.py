"""Conexión a Mongo y arranque compartido por los tests e2e."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv

from app.database import close_mongo_connection, connect_to_mongo

BACKEND_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND_ROOT / ".env")

T = TypeVar("T")


def mongo_configured() -> bool:
    # Misma base que la app cuando no hay .env: mongodb://localhost:27017
    return bool(os.getenv("MONGODB_URL", "mongodb://localhost:27017").strip())


def run_db(work: Callable[[], Awaitable[T]]) -> T:
    """Abre Mongo, ejecuta `work` y cierra la conexión aunque falle."""

    async def _run() -> T:
        await connect_to_mongo()
        try:
            return await work()
        finally:
            await close_mongo_connection()

    return asyncio.run(_run())
