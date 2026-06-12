"""
Prepara «Tienducha» para probar estadísticas Premium en local.

- Plan Premium activo
- approved_at retroactivo (varios meses de historial)
- Visitas al perfil repartidas por mes
- Pedidos completados y pendientes con varias monedas y domicilio

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\seed_tienducha_stats_demo.py
  .\\venv\\Scripts\\python.exe scripts\\seed_tienducha_stats_demo.py --keep-orders
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
    get_seller_profile_views_collection,
)
from app.services.catalog import ensure_catalog_indexes
from app.services.plans import PREMIUM_PLAN_TIER
from app.utils.datetime import to_utc_naive, utc_now

STORE_NAME = "Tienducha"
APPROVED_AT = datetime(2026, 3, 1, 10, 0, 0)


def _calc_subtotals(items: list[dict]) -> list[dict]:
    totals: dict[str, float] = {}
    for item in items:
        currency = item["currency"]
        totals[currency] = totals.get(currency, 0.0) + float(item["line_total"])
    return [
        {"currency": currency, "amount": round(amount, 2)}
        for currency, amount in sorted(totals.items())
    ]


def _make_item(product: dict, quantity: int = 1) -> dict:
    unit_price = float(product["base_price"])
    currency = product["base_currency"]
    return {
        "product_id": str(product["_id"]),
        "name": product["name"],
        "quantity": quantity,
        "unit_price": unit_price,
        "currency": currency,
        "line_total": round(unit_price * quantity, 2),
    }


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return to_utc_naive(day.replace(hour=hour, minute=minute, second=0, microsecond=0))


async def seed_profile_views(seller_id: str) -> int:
    views_col = get_seller_profile_views_collection()
    await views_col.delete_many({"seller_id": seller_id})

    now = to_utc_naive(utc_now())
    docs: list[dict] = []
    month_counts = {
        (2026, 3): 42,
        (2026, 4): 55,
        (2026, 5): 68,
        (2026, 6): 36,
    }

    for (year, month), count in month_counts.items():
        start = datetime(year, month, 5, 9, 0, 0)
        for index in range(count):
            viewed_at = start + timedelta(hours=index * 7, minutes=index * 3)
            if viewed_at > now:
                viewed_at = now - timedelta(hours=count - index)
            docs.append({"seller_id": seller_id, "viewed_at": to_utc_naive(viewed_at)})

    if docs:
        await views_col.insert_many(docs)
    return len(docs)


def _pick_products(products: list[dict], start: int, count: int) -> list[tuple[dict, int]]:
    if not products:
        return []
    picked: list[tuple[dict, int]] = []
    for offset in range(count):
        product = products[(start + offset) % len(products)]
        quantity = 1 + ((start + offset) % 4)
        picked.append((product, quantity))
    return picked


def _build_order_specs(products: list[dict]) -> list[dict]:
    by_currency: dict[str, list[dict]] = {}
    for product in products:
        by_currency.setdefault(product["base_currency"], []).append(product)

    cup_products = by_currency.get("CUP", products)
    usd_products = by_currency.get("USD", products) or cup_products
    mlc_products = by_currency.get("MLC", usd_products) or cup_products
    payment_currencies = ["CUP", "CUP", "USD", "MLC"]

    # (year, month, completed_orders_in_month, max_day)
    months_plan = [
        (2026, 3, 14, 28),
        (2026, 4, 16, 28),
        (2026, 5, 18, 30),
        (2026, 6, 12, 10),
    ]

    specs: list[dict] = []
    order_index = 0

    for year, month, order_count, max_day in months_plan:
        day_step = max(1, max_day // max(order_count, 1))
        for index in range(order_count):
            day = min(1 + index * day_step, max_day)
            hour = 9 + (index % 9)
            minute = (index * 13) % 60
            completed_at = _at(datetime(year, month, day), hour, minute)
            created_at = completed_at - timedelta(hours=1 + (index % 3))

            catalog = cup_products
            if index % 5 == 1:
                catalog = usd_products
            elif index % 7 == 0:
                catalog = mlc_products

            item_count = 1 + (index % 3)
            items = [_make_item(product, qty) for product, qty in _pick_products(catalog, order_index, item_count)]
            order_index += item_count

            with_delivery = index % 3 == 0
            spec: dict = {
                "status": "completed",
                "created_at": created_at,
                "completed_at": completed_at,
                "items": items,
                "payment_currency": payment_currencies[index % len(payment_currencies)],
                "delivery_requested": with_delivery,
            }
            if with_delivery:
                spec["delivery_price"] = float(300 + (index % 4) * 50)
                spec["delivery_currency"] = "CUP"
            specs.append(spec)

    pending_days = [8, 10, 11]
    for index, day in enumerate(pending_days):
        created_at = _at(datetime(2026, 6, day), 11 + index, 20 + index * 5)
        items = [_make_item(cup_products[index % len(cup_products)], 1 + index)]
        specs.append(
            {
                "status": "pending_confirmation",
                "created_at": created_at,
                "completed_at": None,
                "items": items,
                "payment_currency": "CUP" if index % 2 == 0 else None,
                "delivery_requested": index == 1,
            }
        )

    return specs


async def seed_orders(seller_id: str, store_name: str, products: list[dict]) -> tuple[int, int, int]:
    orders_col = get_orders_collection()
    await orders_col.delete_many({"seller_id": seller_id})

    buyer_zone = {
        "province_id": "la-habana",
        "province_name": "La Habana",
        "municipality_id": "plaza-de-la-revolucion",
        "municipality_name": "Plaza de la Revolución",
    }
    delivery = {
        "recipient_name": "Cliente Demo",
        "address": "Calle 23 #456, Vedado",
        "phone_primary": "55512345",
        "phone_secondary": None,
        "notes": "Entregar por la tarde",
    }

    specs = _build_order_specs(products)

    completed = 0
    pending = 0
    products_sold = 0
    for spec in specs:
        items = spec["items"]
        created_at = spec["created_at"]
        updated_at = spec.get("completed_at") or created_at + timedelta(hours=1)
        doc = {
            "seller_id": seller_id,
            "store_name": store_name,
            "status": spec["status"],
            "items": items,
            "subtotals": _calc_subtotals(items),
            "delivery_requested": bool(spec.get("delivery_requested")),
            "delivery": delivery if spec.get("delivery_requested") else None,
            "delivery_price": spec.get("delivery_price"),
            "delivery_currency": spec.get("delivery_currency"),
            "payment_currency": spec.get("payment_currency"),
            "buyer_zone": buyer_zone,
            "created_at": created_at,
            "updated_at": updated_at,
            "completed_at": spec.get("completed_at"),
        }
        await orders_col.insert_one(doc)
        if spec["status"] == "completed":
            completed += 1
            products_sold += sum(int(item["quantity"]) for item in items)
        else:
            pending += 1

    return completed, pending, products_sold


async def seed_product_popularity(seller_id: str, products: list[dict]) -> None:
    products_col = get_catalog_products_collection()
    for index, product in enumerate(products):
        popularity = 8 + (index * 11) % 95
        await products_col.update_one(
            {"_id": product["_id"]},
            {"$set": {"popularity": popularity}},
        )


async def ensure_licuadora_top_in_despensa(seller_id: str) -> None:
    from app.database import get_catalog_categories_collection

    products_col = get_catalog_products_collection()
    categories_col = get_catalog_categories_collection()

    despensa = await categories_col.find_one({"seller_id": seller_id, "name": "Despensa"})
    licuadora = await products_col.find_one({"seller_id": seller_id, "name": "Licuadora Oster"})
    if despensa is None or licuadora is None:
        return

    updates: dict[str, object] = {"updated_at": to_utc_naive(utc_now())}
    if licuadora.get("category_id") != despensa["_id"]:
        updates["category_id"] = despensa["_id"]
        updates["global_category_id"] = "comida"

    top_in_despensa = await products_col.find_one(
        {"seller_id": seller_id, "category_id": despensa["_id"]},
        sort=[("popularity", -1)],
    )
    max_popularity = int(top_in_despensa.get("popularity") or 0) if top_in_despensa else 0
    licuadora_popularity = int(licuadora.get("popularity") or 0)
    if licuadora["_id"] != (top_in_despensa or {}).get("_id") or licuadora_popularity < max_popularity:
        updates["popularity"] = max(max_popularity + 10, 150)

    if len(updates) > 1:
        await products_col.update_one({"_id": licuadora["_id"]}, {"$set": updates})


async def ensure_active_products(seller_id: str) -> int:
    products_col = get_catalog_products_collection()
    active = await products_col.count_documents(
        {
            "seller_id": seller_id,
            "is_available": True,
            "view_only": {"$ne": True},
        }
    )
    if active >= 5:
        return active

    now = to_utc_naive(utc_now())
    sample = [
        ("Licuadora Oster", 4500, "CUP"),
        ("Ventilador recargable", 3200, "CUP"),
        ("Microondas 20L", 185, "USD"),
        ("Martillo", 850, "CUP"),
        ("Café molido", 8, "USD"),
        ("Aceite 900ml", 420, "CUP"),
    ]
    from app.database import get_catalog_categories_collection

    cat_col = get_catalog_categories_collection()
    category = await cat_col.find_one({"seller_id": seller_id})
    if not category:
        result = await cat_col.insert_one(
            {
                "seller_id": seller_id,
                "name": "General",
                "product_count": len(sample),
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        category_id = result.inserted_id
    else:
        category_id = category["_id"]

    for order, (name, price, currency) in enumerate(sample):
        await products_col.insert_one(
            {
                "seller_id": seller_id,
                "category_id": category_id,
                "global_category_id": "hogar",
                "name": name,
                "description": f"Producto demo — {name}",
                "image_url": None,
                "base_price": float(price),
                "base_currency": currency,
                "accepted_currencies": ["CUP"] if currency != "CUP" else [],
                "offers_delivery": True,
                "view_only": False,
                "is_available": True,
                "sort_order": order,
                "created_at": now,
                "updated_at": now,
            }
        )

    return await products_col.count_documents(
        {
            "seller_id": seller_id,
            "is_available": True,
            "view_only": {"$ne": True},
        }
    )


async def main(*, keep_orders: bool) -> None:
    await connect_to_mongo()
    await ensure_catalog_indexes()

    registration = await get_registrations_collection().find_one({"store_name": STORE_NAME})
    if not registration:
        print(f"No se encontró la tienda «{STORE_NAME}».")
        await close_mongo_connection()
        return

    seller_id = str(registration["_id"])
    now = to_utc_naive(utc_now())
    subscription_end = now + timedelta(days=365)

    await get_registrations_collection().update_one(
        {"_id": registration["_id"]},
        {
            "$set": {
                "plan_tier": PREMIUM_PLAN_TIER,
                "approved_at": APPROVED_AT,
                "subscription_starts_at": APPROVED_AT,
                "subscription_ends_at": subscription_end,
                "updated_at": now,
            }
        },
    )
    print(f"[OK] Plan Premium hasta {subscription_end.date()} (approved_at: {APPROVED_AT.date()})")

    active_products = await ensure_active_products(seller_id)
    print(f"[OK] Productos activos disponibles: {active_products}")

    products = await get_catalog_products_collection().find(
        {"seller_id": seller_id, "is_available": True, "view_only": {"$ne": True}}
    ).to_list(50)

    if not keep_orders:
        completed, pending, products_sold = await seed_orders(seller_id, STORE_NAME, products)
        print(f"[OK] Pedidos demo: {completed} completados, {pending} pendientes")
        print(f"[OK] Unidades vendidas (completados): {products_sold}")
        await seed_product_popularity(seller_id, products)
        print(f"[OK] Popularidad asignada a {len(products)} productos")
    else:
        print("· Pedidos existentes conservados (--keep-orders)")

    await ensure_licuadora_top_in_despensa(seller_id)
    print("[OK] Licuadora Oster destacada en Despensa")

    if not keep_orders:
        for year, month in ((2026, 3), (2026, 4), (2026, 5), (2026, 6)):
            from app.services.seller_stats import get_seller_products_sold_chart

            reg = await get_registrations_collection().find_one({"_id": registration["_id"]})
            chart = await get_seller_products_sold_chart(
                seller_id,
                reg,
                granularity="daily",
                year=year,
                month=month,
            )
            print(f"     {month:02d}/{year}: {chart.total} productos vendidos")

    view_count = await seed_profile_views(seller_id)
    print(f"[OK] Visitas al perfil: {view_count}")

    print(f"\nListo. Inicia sesión como «{STORE_NAME}» y abre /tienda (General).")
    await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed de estadísticas para Tienducha")
    parser.add_argument(
        "--keep-orders",
        action="store_true",
        help="No reemplazar pedidos existentes",
    )
    args = parser.parse_args()
    asyncio.run(main(keep_orders=args.keep_orders))
