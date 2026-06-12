"""Asegura Licuadora Oster como producto más popular en Despensa (Tienducha)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo, get_registrations_collection
from scripts.seed_tienducha_stats_demo import ensure_licuadora_top_in_despensa


async def main() -> None:
    await connect_to_mongo()
    reg = await get_registrations_collection().find_one({"store_name": "Tienducha"})
    if not reg:
        print("No se encontró Tienducha.")
        return
    await ensure_licuadora_top_in_despensa(str(reg["_id"]))
    print("Listo: Licuadora Oster destacada en Despensa.")
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
