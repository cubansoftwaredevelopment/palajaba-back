"""
Diagnóstico: compara productos visibles en marketplace vs catálogo público de tienda.

Semilla ~25 tiendas con escenarios distintos y reporta desajustes (marketplace > 0, catálogo = 0).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\diagnose_store_catalog_vs_marketplace.py
  .\\venv\\Scripts\\python.exe scripts\\diagnose_store_catalog_vs_marketplace.py --skip-seed
  .\\venv\\Scripts\\python.exe scripts\\diagnose_store_catalog_vs_marketplace.py --scan-all
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from bson import ObjectId

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_registrations_collection,
)
from app.services.marketplace import (
    _build_marketplace_products_query,
    _build_marketplace_seller_context,
    _seller_store_product_query,
    get_store_catalog,
)
from app.utils.datetime import to_utc_naive, utc_now

MARKER = "store_catalog_diagnose_v1"
PROVINCE_ID = "la-habana"
LOCAL_MUNICIPALITY_ID = "playa"
REMOTE_MUNICIPALITY_ID = "marianao"


def unique_phone(seed: str) -> str:
    return f"{int.from_bytes(seed.encode(), 'big') % 100000000:08d}"


def seller_doc(
    *,
    oid: ObjectId,
    store_name: str,
    store_slug: str,
    municipality_id: str = LOCAL_MUNICIPALITY_ID,
    offers_delivery: bool = True,
    with_delivery_area: bool = True,
) -> dict:
    now = to_utc_naive(utc_now())
    doc = {
        "_id": oid,
        "status": "approved",
        "transfer_id": f"TEST-DIAG-{store_slug}",
        "store_name": store_name,
        "store_slug": store_slug,
        "phone": unique_phone(store_slug),
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": offers_delivery,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": municipality_id,
            "municipality_name": "Playa" if municipality_id == LOCAL_MUNICIPALITY_ID else "Marianao",
        },
        "subscription_starts_at": now - timedelta(days=5),
        "subscription_ends_at": now + timedelta(days=25),
        "store_catalog_diagnose_marker": MARKER,
    }
    if with_delivery_area and offers_delivery:
        doc["delivery_areas"] = [
            {
                "province_id": PROVINCE_ID,
                "province_name": "La Habana",
                "municipality_id": REMOTE_MUNICIPALITY_ID,
                "municipality_name": "Marianao",
            }
        ]
    else:
        doc["delivery_areas"] = []
    return doc


def product_doc(
    *,
    oid: ObjectId,
    seller_id: str,
    category_id: ObjectId | str | None,
    name: str,
    offers_delivery: bool = True,
    view_only: bool = False,
    is_available: bool = True,
    seller_id_type: str = "str",
) -> dict:
    now = to_utc_naive(utc_now())
    sid: str | ObjectId = ObjectId(seller_id) if seller_id_type == "objectid" else seller_id
    cid = category_id
    if isinstance(category_id, str) and category_id and len(category_id) == 24:
        cid = category_id  # keep string on purpose for mismatch scenarios
    doc = {
        "_id": oid,
        "seller_id": sid,
        "category_id": cid,
        "name": name,
        "description": "Diagnóstico",
        "image_url": "https://example.com/p.jpg",
        "base_price": 100.0,
        "base_currency": "CUP",
        "accepted_currencies": ["CUP"],
        "offers_delivery": offers_delivery,
        "view_only": view_only,
        "is_available": is_available,
        "global_category_id": "food",
        "store_catalog_diagnose_marker": MARKER,
        "created_at": now,
        "updated_at": now,
    }
    return doc


@dataclass
class Scenario:
    slug: str
    name: str
    note: str


SCENARIOS = [
    Scenario("diag-normal", "DIAG Normal", "Categoría y producto alineados"),
    Scenario("diag-pickup-only", "DIAG Pickup only", "Sin domicilio, comprador remoto"),
    Scenario("diag-view-only", "DIAG View only", "Solo vista"),
    Scenario("diag-no-categories", "DIAG Sin categorías", "Productos sin docs de categoría local"),
    Scenario("diag-orphan-category", "DIAG Categoría huérfana", "category_id apunta a categoría borrada"),
    Scenario("diag-null-category", "DIAG category_id null", "Productos sin category_id, tienda CON categorías"),
    Scenario("diag-catid-string", "DIAG category_id string", "category_id guardado como string, no ObjectId"),
    Scenario("diag-sellerid-oid", "DIAG seller_id ObjectId", "seller_id en producto como ObjectId"),
    Scenario("diag-empty-categories", "DIAG Categorías vacías", "Categorías existen pero productos en otra"),
    Scenario("diag-mixed-delivery", "DIAG Mixto domicilio", "Algunos con/sin domicilio"),
]


async def cleanup() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()
    await products.delete_many({"store_catalog_diagnose_marker": MARKER})
    await categories.delete_many({"store_catalog_diagnose_marker": MARKER})
    await registrations.delete_many({"store_catalog_diagnose_marker": MARKER})


async def seed_scenarios() -> None:
    products = get_catalog_products_collection()
    categories = get_catalog_categories_collection()
    registrations = get_registrations_collection()

    async def add_category(seller_id: str, name: str = "Principal") -> ObjectId:
        cid = ObjectId()
        await categories.insert_one(
            {
                "_id": cid,
                "seller_id": seller_id,
                "name": name,
                "sort_order": 0,
                "store_catalog_diagnose_marker": MARKER,
            }
        )
        return cid

    # 1 Normal
    s1 = ObjectId()
    sid1 = str(s1)
    c1 = ObjectId()
    await registrations.insert_one(seller_doc(oid=s1, store_name="DIAG Normal", store_slug="diag-normal"))
    await categories.insert_one(
        {"_id": c1, "seller_id": sid1, "name": "Principal", "sort_order": 0, "store_catalog_diagnose_marker": MARKER}
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid1, category_id=c1, name="Normal A", offers_delivery=True)
    )

    # 2 Pickup only store
    s2 = ObjectId()
    sid2 = str(s2)
    c2 = await add_category(sid2)
    await registrations.insert_one(
        seller_doc(
            oid=s2,
            store_name="DIAG Pickup only",
            store_slug="diag-pickup-only",
            offers_delivery=False,
            with_delivery_area=False,
        )
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid2, category_id=c2, name="Pickup A", offers_delivery=False)
    )

    # 3 View only
    s3 = ObjectId()
    sid3 = str(s3)
    c3 = await add_category(sid3)
    await registrations.insert_one(seller_doc(oid=s3, store_name="DIAG View only", store_slug="diag-view-only"))
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid3, category_id=c3, name="View A", view_only=True, offers_delivery=False)
    )

    # 4 No categories
    s4 = ObjectId()
    sid4 = str(s4)
    orphan_c = ObjectId()
    await registrations.insert_one(
        seller_doc(oid=s4, store_name="DIAG Sin categorías", store_slug="diag-no-categories")
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid4, category_id=orphan_c, name="Sin cat A")
    )

    # 5 Orphan category (deleted category doc)
    s5 = ObjectId()
    sid5 = str(s5)
    deleted_c = ObjectId()
    await registrations.insert_one(
        seller_doc(oid=s5, store_name="DIAG Categoría huérfana", store_slug="diag-orphan-category")
    )
    await add_category(sid5, "Visible vacía")
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid5, category_id=deleted_c, name="Huérfano A", offers_delivery=False)
    )

    # 6 Null category_id with categories present — THE LIKELY PRODUCTION BUG
    s6 = ObjectId()
    sid6 = str(s6)
    c6 = await add_category(sid6)
    await registrations.insert_one(
        seller_doc(oid=s6, store_name="DIAG category_id null", store_slug="diag-null-category")
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid6, category_id=None, name="Null cat A")
    )
    # also one valid product to see partial catalog
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid6, category_id=c6, name="Null cat B válido")
    )

    # 7 category_id as string
    s7 = ObjectId()
    sid7 = str(s7)
    c7 = await add_category(sid7)
    await registrations.insert_one(
        seller_doc(oid=s7, store_name="DIAG category_id string", store_slug="diag-catid-string")
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid7, category_id=str(c7), name="String cat A")
    )

    # 8 seller_id as ObjectId in product
    s8 = ObjectId()
    sid8 = str(s8)
    c8 = await add_category(sid8)
    await registrations.insert_one(
        seller_doc(oid=s8, store_name="DIAG seller_id ObjectId", store_slug="diag-sellerid-oid")
    )
    await products.insert_one(
        product_doc(
            oid=ObjectId(),
            seller_id=sid8,
            category_id=c8,
            name="OID seller A",
            seller_id_type="objectid",
        )
    )

    # 9 Empty categories, product in orphan
    s9 = ObjectId()
    sid9 = str(s9)
    orphan9 = ObjectId()
    await registrations.insert_one(
        seller_doc(oid=s9, store_name="DIAG Categorías vacías", store_slug="diag-empty-categories")
    )
    await add_category(sid9, "Vacía 1")
    await add_category(sid9, "Vacía 2")
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid9, category_id=orphan9, name="En otra cat")
    )

    # 10 Mixed delivery
    s10 = ObjectId()
    sid10 = str(s10)
    c10 = await add_category(sid10)
    await registrations.insert_one(
        seller_doc(oid=s10, store_name="DIAG Mixto domicilio", store_slug="diag-mixed-delivery")
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid10, category_id=c10, name="Con domicilio", offers_delivery=True)
    )
    await products.insert_one(
        product_doc(oid=ObjectId(), seller_id=sid10, category_id=c10, name="Sin domicilio", offers_delivery=False)
    )

    # Extra bulk: 15 normal stores
    for i in range(1, 16):
        sx = ObjectId()
        sidx = str(sx)
        cx = ObjectId()
        slug = f"diag-bulk-{i:02d}"
        await registrations.insert_one(
            seller_doc(oid=sx, store_name=f"DIAG Bulk {i:02d}", store_slug=slug)
        )
        await categories.insert_one(
            {
                "_id": cx,
                "seller_id": sidx,
                "name": "Catálogo",
                "sort_order": 0,
                "store_catalog_diagnose_marker": MARKER,
            }
        )
        for j in range(1, 4):
            await products.insert_one(
                product_doc(
                    oid=ObjectId(),
                    seller_id=sidx,
                    category_id=cx,
                    name=f"Bulk {i}-{j}",
                )
            )


async def analyze_product_data(seller_id: str) -> dict:
    products_col = get_catalog_products_collection()
    categories_col = get_catalog_categories_collection()

    categories = await categories_col.find({"seller_id": seller_id}).to_list(length=None)
    known_ids = {doc["_id"] for doc in categories}

    products = await products_col.find({"seller_id": seller_id}).to_list(length=None)
    # also ObjectId seller_id variant
    try:
        oid_products = await products_col.find({"seller_id": ObjectId(seller_id)}).to_list(length=None)
    except Exception:
        oid_products = []

    all_products = products + [p for p in oid_products if p["_id"] not in {x["_id"] for x in products}]

    issues: list[str] = []
    null_cat = 0
    orphan_cat = 0
    string_cat = 0
    oid_seller = 0

    for p in all_products:
        if isinstance(p.get("seller_id"), ObjectId):
            oid_seller += 1
        cid = p.get("category_id")
        if cid is None:
            null_cat += 1
        elif isinstance(cid, str):
            string_cat += 1
            try:
                if ObjectId(cid) not in known_ids:
                    orphan_cat += 1
            except Exception:
                orphan_cat += 1
        elif cid not in known_ids:
            orphan_cat += 1

    if null_cat:
        issues.append(f"{null_cat} producto(s) con category_id=null")
    if orphan_cat:
        issues.append(f"{orphan_cat} producto(s) con category_id huérfano")
    if string_cat:
        issues.append(f"{string_cat} producto(s) con category_id string")
    if oid_seller:
        issues.append(f"{oid_seller} producto(s) con seller_id ObjectId")

    return {
        "categories": len(categories),
        "products": len(all_products),
        "available": sum(1 for p in all_products if p.get("is_available", True)),
        "issues": issues,
    }


async def count_marketplace_products(
    seller_id: str,
    province_id: str,
    municipality_id: str,
) -> int:
    products_col = get_catalog_products_collection()
    _, local_ids, delivery_ids, pickup_ids = await _build_marketplace_seller_context(
        province_id,
        municipality_id,
    )
    query = _build_marketplace_products_query(
        local_ids,
        delivery_ids,
        pickup_seller_ids=pickup_ids or None,
    )
    return await products_col.count_documents({**query, "seller_id": seller_id})


async def count_raw_store_products(
    seller_id: str,
    seller: dict,
    province_id: str,
    municipality_id: str,
) -> int:
    products_col = get_catalog_products_collection()
    q = _seller_store_product_query(seller_id, seller, province_id, municipality_id)
    return await products_col.count_documents(q)


async def evaluate_store(
    slug: str,
    province_id: str,
    municipality_id: str,
) -> dict:
    registrations = get_registrations_collection()
    seller = await registrations.find_one({"store_slug": slug})
    if not seller:
        return {"slug": slug, "error": "no encontrada"}

    seller_id = str(seller["_id"])
    data = await analyze_product_data(seller_id)

    market_count = await count_marketplace_products(seller_id, province_id, municipality_id)
    raw_count = await count_raw_store_products(seller_id, seller, province_id, municipality_id)

    catalog = await get_store_catalog(slug, province_id, municipality_id, limit_per_category=50)
    catalog_count = catalog.total_products
    catalog_visible = sum(len(s.products) for s in catalog.sections)

    mismatch = market_count > 0 and catalog_count == 0
    partial = market_count > 0 and 0 < catalog_count < raw_count

    return {
        "slug": slug,
        "name": seller.get("store_name"),
        "marketplace": market_count,
        "raw_store_query": raw_count,
        "catalog_total": catalog_count,
        "catalog_visible": catalog_visible,
        "sections": len(catalog.sections),
        "mismatch": mismatch,
        "partial": partial,
        "data_issues": data["issues"],
        "categories": data["categories"],
        "products_db": data["products"],
    }


async def scan_all_sellers(province_id: str, municipality_id: str) -> list[dict]:
    registrations = get_registrations_collection()
    sellers = await registrations.find({"status": "approved"}).to_list(length=500)
    results = []
    for seller in sellers:
        slug = seller.get("store_slug")
        if not slug:
            continue
        try:
            row = await evaluate_store(slug, province_id, municipality_id)
            if row.get("mismatch") or row.get("partial") or row.get("data_issues"):
                results.append(row)
        except Exception as exc:
            results.append({"slug": slug, "name": seller.get("store_name"), "error": str(exc)})
    return results


def print_report(rows: list[dict], title: str) -> None:
    print(f"\n{'=' * 72}")
    print(title)
    print(f"{'=' * 72}")
    mismatches = [r for r in rows if r.get("mismatch")]
    partials = [r for r in rows if r.get("partial")]
    print(f"Tiendas analizadas: {len(rows)}")
    print(f"Desajuste total (marketplace>0, catálogo=0): {len(mismatches)}")
    print(f"Desajuste parcial (catálogo < productos en BD): {len(partials)}")

    for row in rows:
        if row.get("error"):
            print(f"\n  ! {row.get('slug')}: ERROR {row['error']}")
            continue
        flag = ""
        if row.get("mismatch"):
            flag = " *** BUG ***"
        elif row.get("partial"):
            flag = " * parcial *"
        print(
            f"\n  {row['name']} ({row['slug']}){flag}\n"
            f"    marketplace={row['marketplace']} | raw_query={row['raw_store_query']} | "
            f"catalog_total={row['catalog_total']} | sections={row['sections']}\n"
            f"    categorías locales={row['categories']} | productos BD={row['products_db']}"
        )
        if row.get("data_issues"):
            print(f"    datos: {'; '.join(row['data_issues'])}")


async def main(skip_seed: bool, scan_all: bool) -> int:
    await connect_to_mongo()
    try:
        if not skip_seed:
            await cleanup()
            await seed_scenarios()
            print("Semilla de diagnóstico insertada (25 tiendas).")

        if scan_all:
            rows = await scan_all_sellers(PROVINCE_ID, REMOTE_MUNICIPALITY_ID)
            print_report(rows, "Escaneo de TODAS las tiendas aprobadas (comprador: Marianao)")
        else:
            slugs = [s.slug for s in SCENARIOS] + [f"diag-bulk-{i:02d}" for i in range(1, 16)]
            rows = []
            for slug in slugs:
                rows.append(await evaluate_store(slug, PROVINCE_ID, REMOTE_MUNICIPALITY_ID))
            print_report(rows, "Escenarios sembrados (comprador remoto: Marianao)")

        # Also test local buyer for problematic scenarios
        problem_slugs = ["diag-null-category", "diag-catid-string", "diag-orphan-category", "diag-sellerid-oid"]
        print(f"\n{'=' * 72}")
        print("Repetición comprador LOCAL (Playa) en escenarios problemáticos")
        print(f"{'=' * 72}")
        for slug in problem_slugs:
            row = await evaluate_store(slug, PROVINCE_ID, LOCAL_MUNICIPALITY_ID)
            print(
                f"  {slug}: marketplace={row.get('marketplace')} catalog={row.get('catalog_total')} "
                f"issues={row.get('data_issues')}"
            )

        mismatches = [r for r in rows if r.get("mismatch")] if not scan_all else []
        return 1 if mismatches else 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--scan-all", action="store_true", help="Escanear tiendas reales en BD")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.skip_seed, args.scan_all)))
