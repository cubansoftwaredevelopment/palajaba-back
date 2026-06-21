"""
Repara productos con category_id null/huérfano para que aparezcan en el catálogo público.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\repair_store_catalog.py --slug mi-tienda
  .\\venv\\Scripts\\python.exe scripts\\repair_store_catalog.py --all
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.database import close_mongo_connection, connect_to_mongo
from app.services.store_catalog_repair import (
    repair_all_store_catalog_products,
    repair_store_catalog_by_slug,
)


def print_result(result) -> None:
    print(
        f"  {result.store_name or result.seller_id} ({result.store_slug or 'sin slug'}): "
        f"null={result.fixed_null_category}, huérfanos={result.fixed_orphan_category}, "
        f"string={result.fixed_string_category}, seller_id={result.fixed_seller_id_type}"
    )


async def main(slug: str | None, repair_all: bool) -> int:
    await connect_to_mongo()
    try:
        if slug:
            result = await repair_store_catalog_by_slug(slug)
            print("Reparación completada:")
            print_result(result)
            if result.total_fixed == 0:
                print("  (sin cambios necesarios)")
            return 0

        if repair_all:
            results = await repair_all_store_catalog_products()
            print(f"Reparación global: {len(results)} tienda(s) con cambios.")
            for result in results:
                print_result(result)
            if not results:
                print("  (sin cambios necesarios)")
            return 0

        print("Indica --slug <slug> o --all")
        return 1
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reparar category_id de productos para catálogo público")
    parser.add_argument("--slug", help="Slug de la tienda a reparar")
    parser.add_argument("--all", action="store_true", help="Reparar todas las tiendas")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.slug, args.all)))
