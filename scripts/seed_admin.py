"""
Inserta el usuario administrador en MongoDB.

Uso (desde la carpeta backend):
  .\\venv\\Scripts\\python.exe scripts\\seed_admin.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo
from app.services.admins import seed_default_admin


async def main() -> None:
    await connect_to_mongo()
    created = await seed_default_admin()
    if created:
        print("Admin creado correctamente.")
    else:
        print("El admin ya existía; no se modificó.")
    print(f"  Usuario: {settings.admin_username}")
    print(f"  Contraseña: (valor de ADMIN_PASSWORD en .env)")
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
