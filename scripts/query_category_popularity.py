"""Consulta popularidad por categoría global en un municipio (mismo criterio que el home)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo
from app.services.marketplace import (
    _aggregate_category_stats,
    _display_category_name,
    _get_visible_sellers,
    _sort_category_ids,
)


async def main() -> None:
    province_id = sys.argv[1] if len(sys.argv) > 1 else "la-habana"
    municipality_id = sys.argv[2] if len(sys.argv) > 2 else "plaza-de-la-revolucion"

    await connect_to_mongo()
    sellers = await _get_visible_sellers(province_id, municipality_id)
    print(f"Municipio: {municipality_id} ({province_id})")
    print(f"Tiendas visibles: {len(sellers)}")
    for doc in sellers.values():
        print(f"  - {doc.get('store_name')}")

    stats = await _aggregate_category_stats(list(sellers.keys()))
    if not stats:
        print("Sin categorías con productos.")
        await close_mongo_connection()
        return

    print("\nCategorias en el home (orden de aparicion):")
    for rank, category_id in enumerate(_sort_category_ids(stats), start=1):
        row = stats[category_id]
        print(
            f"{rank}. {_display_category_name(category_id)} [{category_id}] "
            f"- popularidad total: {row['popularity']}, productos: {row['count']}"
        )

    from app.database import get_catalog_products_collection
    from app.services.marketplace import _base_product_filter

    products_col = get_catalog_products_collection()
    cursor = products_col.find({**_base_product_filter(list(sellers.keys()))})
    by_category: dict[str, list[tuple[str, int]]] = {}
    async for doc in cursor:
        category_id = str(doc.get("global_category_id") or "otros")
        by_category.setdefault(category_id, []).append(
            (str(doc.get("name") or ""), int(doc.get("popularity") or 0)),
        )

    print("\nDetalle por producto:")
    for category_id in _sort_category_ids(stats):
        items = by_category.get(category_id, [])
        print(f"\n{_display_category_name(category_id)} [{category_id}]")
        for name, popularity in sorted(items, key=lambda item: -item[1]):
            print(f"  {popularity:>3} pts - {name}")

    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
