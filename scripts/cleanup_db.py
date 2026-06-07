"""
Limpia la base de datos conservando solo los usuarios admin.

Uso (desde la carpeta backend):
  .\\venv\\Scripts\\python.exe scripts\\cleanup_db.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo

KEEP_COLLECTIONS = {"admins"}


async def main() -> None:
    await connect_to_mongo()

    collection_names = await database.db.list_collection_names()
    print(f"Base de datos: {settings.database_name}")

    for name in sorted(collection_names):
        if name in KEEP_COLLECTIONS:
            count = await database.db[name].count_documents({})
            print(f"  [conservada] {name}: {count} documento(s)")
            continue

        result = await database.db[name].delete_many({})
        print(f"  [limpiada]   {name}: {result.deleted_count} eliminado(s)")

    await close_mongo_connection()
    print("Limpieza completada.")


if __name__ == "__main__":
    asyncio.run(main())
