"""
Tests de visibilidad: productos sin domicilio no deben verse fuera del municipio de la tienda.

Uso (desde backend/, tras seed_delivery_visibility_demo.py):
  .\\venv\\Scripts\\python.exe scripts\\test_delivery_visibility.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.schemas.marketplace import JabaSyncItemRequest, JabaSyncRequest
from app.services.marketplace import (
    _build_marketplace_products_query,
    _get_visible_sellers,
    _seller_is_local_to_municipality,
    _seller_store_product_query,
    _split_sellers_by_locality,
    list_home_feed,
    sync_jaba_products,
)

DELIVERY_TEST_MARKER = "delivery_visibility_test_v1"
TEST_WITH_DELIVERY = "TEST domicilio Sí"
TEST_WITHOUT_DELIVERY = "TEST domicilio No"

BUYER_SCENARIOS = [
    ("marianao", "Marianao"),
    ("plaza-de-la-revolucion", "Plaza de la Revolución"),
    ("centro-habana", "Centro Habana"),
]

TEST_STORE_NAMES = [
    "Tienducha",
    "Mercado Centro",
    "Bodega Playa",
    "Variedades Marianao",
]


class TestFailure(Exception):
    pass


async def _test_products_for_buyer(
    province_id: str,
    municipality_id: str,
    municipality_label: str,
) -> list[str]:
    errors: list[str] = []
    products_col = get_catalog_products_collection()
    registrations = get_registrations_collection()

    seller_by_id = await _get_visible_sellers(province_id, municipality_id)
    local_ids, delivery_ids = _split_sellers_by_locality(
        seller_by_id, province_id, municipality_id
    )
    query = _build_marketplace_products_query(local_ids, delivery_ids)

    print(f"\n{'=' * 60}")
    print(f"Comprador: {municipality_label} ({municipality_id})")
    print(f"Tiendas locales: {len(local_ids)} | envío desde otro municipio: {len(delivery_ids)}")

    if delivery_ids:
        remote_visible = await products_col.find(
            {**query, "seller_id": {"$in": delivery_ids}}
        ).to_list(500)
        pickup_only_remote = [p for p in remote_visible if not p.get("offers_delivery")]
        if pickup_only_remote:
            names = [p["name"] for p in pickup_only_remote[:5]]
            errors.append(
                f"{municipality_label}: marketplace muestra {len(pickup_only_remote)} "
                f"producto(s) sin domicilio de tiendas remotas: {names}"
            )
        else:
            print(
                f"  OK marketplace: 0 sin domicilio en tiendas remotas "
                f"({len(remote_visible)} productos con domicilio visibles)"
            )

    for store_name in TEST_STORE_NAMES:
        seller = await registrations.find_one({"store_name": store_name})
        if seller is None:
            continue
        seller_id = str(seller["_id"])
        if seller_id not in seller_by_id:
            print(f"\n  — {store_name}: no visible para este comprador —")
            continue

        is_local = _seller_is_local_to_municipality(seller, province_id, municipality_id)
        role = "local" if is_local else "envío"
        print(f"\n  — {store_name} ({role}) —")

        with_yes = await products_col.find_one(
            {
                "seller_id": seller_id,
                "delivery_test_marker": DELIVERY_TEST_MARKER,
                "name": TEST_WITH_DELIVERY,
            }
        )
        with_no = await products_col.find_one(
            {
                "seller_id": seller_id,
                "delivery_test_marker": DELIVERY_TEST_MARKER,
                "name": TEST_WITHOUT_DELIVERY,
            }
        )
        if not with_yes or not with_no:
            errors.append(f"{store_name}: faltan productos TEST (ejecuta seed_delivery_visibility_demo.py)")
            continue

        market_yes = await products_col.count_documents({**query, "_id": with_yes["_id"]})
        market_no = await products_col.count_documents({**query, "_id": with_no["_id"]})

        store_query = _seller_store_product_query(
            seller_id, seller, province_id, municipality_id
        )
        catalog_yes = await products_col.count_documents({**store_query, "_id": with_yes["_id"]})
        catalog_no = await products_col.count_documents({**store_query, "_id": with_no["_id"]})

        if is_local:
            if not market_yes or not market_no:
                errors.append(
                    f"{store_name} en {municipality_label} (local): deben verse ambos TEST "
                    f"(sí={market_yes}, no={market_no})"
                )
            else:
                print("    OK local: ambos TEST visibles en marketplace y catálogo")
        else:
            if not market_yes:
                errors.append(
                    f"{store_name} en {municipality_label} (envío): «{TEST_WITH_DELIVERY}» debe verse"
                )
            if market_no:
                errors.append(
                    f"{store_name} en {municipality_label} (envío): «{TEST_WITHOUT_DELIVERY}» "
                    "NO debe verse en marketplace"
                )
            if not catalog_yes:
                errors.append(
                    f"{store_name} catálogo en {municipality_label}: «{TEST_WITH_DELIVERY}» debe verse"
                )
            if catalog_no:
                errors.append(
                    f"{store_name} catálogo en {municipality_label}: «{TEST_WITHOUT_DELIVERY}» NO debe verse"
                )
            if market_yes and not market_no and catalog_yes and not catalog_no:
                print("    OK envío: solo TEST con domicilio visible")

    return errors


async def _test_jaba_sync() -> list[str]:
    errors: list[str] = []
    products_col = get_catalog_products_collection()
    registrations = get_registrations_collection()

    tienducha = await registrations.find_one({"store_name": "Tienducha"})
    if tienducha is None:
        return ["Tienducha no encontrada"]

    pickup_product = await products_col.find_one(
        {
            "seller_id": str(tienducha["_id"]),
            "name": TEST_WITHOUT_DELIVERY,
            "delivery_test_marker": DELIVERY_TEST_MARKER,
        }
    )
    if pickup_product is None:
        return ["Producto TEST domicilio No de Tienducha no encontrado"]

    payload = JabaSyncRequest(
        items=[
            JabaSyncItemRequest(
                product_id=str(pickup_product["_id"]),
                name=pickup_product["name"],
            )
        ],
        province_id="la-habana",
        municipality_id="marianao",
    )
    result = await sync_jaba_products(payload)

    if result.valid:
        errors.append("Jaba sync: producto sin domicilio no debería ser válido en Marianao")
    elif not result.removed or result.removed[0].reason != "no_delivery":
        reason = result.removed[0].reason if result.removed else "none"
        errors.append(f"Jaba sync: se esperaba reason=no_delivery, got {reason}")
    else:
        print("\n  OK jaba sync: producto sin domicilio rechazado (no_delivery)")

    return errors


async def _test_home_feed() -> list[str]:
    errors: list[str] = []
    feed = await list_home_feed("la-habana", "marianao", limit_per_category=50)
    product_ids = {p.id for section in feed.sections for p in section.products}

    products_col = get_catalog_products_collection()
    registrations = get_registrations_collection()
    pickup_remote = await products_col.find(
        {
            "delivery_test_marker": DELIVERY_TEST_MARKER,
            "name": TEST_WITHOUT_DELIVERY,
            "offers_delivery": False,
        }
    ).to_list(20)

    for doc in pickup_remote:
        pid = str(doc["_id"])
        seller_id = doc.get("seller_id")
        try:
            seller_oid = ObjectId(seller_id) if not isinstance(seller_id, ObjectId) else seller_id
        except Exception:
            continue
        seller = await registrations.find_one({"_id": seller_oid})
        if seller and not _seller_is_local_to_municipality(seller, "la-habana", "marianao"):
            if pid in product_ids:
                errors.append(
                    f"Home feed Marianao: «{TEST_WITHOUT_DELIVERY}» de {seller.get('store_name')} "
                    "no debe aparecer"
                )

    if not errors:
        print("\n  OK home feed Marianao: ningún TEST sin domicilio remoto")
    return errors


async def main() -> None:
    await connect_to_mongo()

    marker_count = await get_catalog_products_collection().count_documents(
        {"delivery_test_marker": DELIVERY_TEST_MARKER}
    )
    if marker_count == 0:
        print("ERROR: No hay productos TEST. Ejecuta: scripts/seed_delivery_visibility_demo.py")
        await close_mongo_connection()
        sys.exit(1)

    print(f"Productos TEST en BD: {marker_count}")
    all_errors: list[str] = []

    for municipality_id, label in BUYER_SCENARIOS:
        all_errors.extend(await _test_products_for_buyer("la-habana", municipality_id, label))

    all_errors.extend(await _test_jaba_sync())
    all_errors.extend(await _test_home_feed())

    await close_mongo_connection()

    print(f"\n{'=' * 60}")
    if all_errors:
        print(f"FALLÓ: {len(all_errors)} error(es)\n")
        for err in all_errors:
            print(f"  • {err}")
        sys.exit(1)

    print("TODOS LOS TESTS PASARON")
    print("Visibilidad por domicilio a nivel producto funciona correctamente.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except TestFailure as exc:
        print(f"\nFALLÓ: {exc}")
        sys.exit(1)
