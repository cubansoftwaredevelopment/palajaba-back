"""Verifica filtro offers_delivery por producto para compradores fuera del municipio del vendedor."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.services.marketplace import (
    _build_marketplace_products_query,
    _get_visible_sellers,
    _seller_is_local_to_municipality,
    _seller_store_product_query,
    _split_sellers_by_locality,
)


async def main() -> None:
    await connect_to_mongo()

    # Comprador en Marianao; tiendas en Plaza que envían a Marianao
    buyer_province = "la-habana"
    buyer_municipality = "marianao"

    seller_by_id = await _get_visible_sellers(buyer_province, buyer_municipality)
    local_ids, delivery_ids = _split_sellers_by_locality(
        seller_by_id, buyer_province, buyer_municipality
    )

    print(f"Comprador: {buyer_municipality} ({buyer_province})")
    print(f"Tiendas locales: {len(local_ids)} | con envío desde otro municipio: {len(delivery_ids)}")

    query = _build_marketplace_products_query(local_ids, delivery_ids)
    products_col = get_catalog_products_collection()

    for seller_id in delivery_ids[:3]:
        seller = seller_by_id[seller_id]
        print(f"\n--- {seller.get('store_name')} (envío a {buyer_municipality}) ---")
        area = seller.get("business_area") or {}
        print(f"    Ubicación tienda: {area.get('municipality_id')}")

        all_products = await products_col.find({"seller_id": seller_id}).to_list(50)
        visible = await products_col.find({**query, "seller_id": seller_id}).to_list(50)

        without_delivery = [p for p in all_products if not p.get("offers_delivery")]
        leaked = [p for p in without_delivery if p["_id"] in {v["_id"] for v in visible}]

        print(f"    Total catálogo: {len(all_products)}")
        print(f"    Sin domicilio en producto: {len(without_delivery)}")
        print(f"    Visibles en marketplace: {len(visible)}")
        if without_delivery:
            names = ", ".join(p["name"] for p in without_delivery[:5])
            print(f"    Ej. sin domicilio: {names}")
        if leaked:
            print(f"    ERROR: productos sin domicilio visibles: {[p['name'] for p in leaked]}")
        else:
            print("    OK: ningún producto sin domicilio aparece fuera de su municipio")

        store_query = _seller_store_product_query(
            seller_id,
            seller,
            buyer_province,
            buyer_municipality,
        )
        store_visible = await products_col.find(store_query).to_list(50)
        store_pickup_only = [p for p in without_delivery if p["_id"] in {v["_id"] for v in store_visible}]
        if store_pickup_only:
            print(
                f"    OK catálogo tienda: {len(store_pickup_only)} producto(s) solo recogida visibles"
            )
        else:
            print("    OK catálogo tienda público")

    # Tienducha específico si existe
    tienducha = await get_registrations_collection().find_one({"store_name": "Tienducha"})
    if tienducha:
        sid = str(tienducha["_id"])
        pintura = await products_col.find_one({"seller_id": sid, "name": "Pintura blanca 1 galón"})
        if pintura and sid in delivery_ids:
            in_market = await products_col.count_documents({**query, "_id": pintura["_id"]})
            print(f"\nTienducha «Pintura blanca 1 galón» (offers_delivery={pintura.get('offers_delivery')})")
            print(f"    En marketplace para {buyer_municipality}: {'SÍ (mal)' if in_market else 'NO (correcto)'}")

    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
