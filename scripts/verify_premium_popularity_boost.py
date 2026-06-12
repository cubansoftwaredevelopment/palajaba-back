"""Verifica multiplicador x2 de popularidad para vendedores Premium."""

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
from app.services.plans import PREMIUM_RECOMMENDATION_MULTIPLIER, recommendation_multiplier
from app.services.product_popularity import (
    POPULARITY_DELTA,
    bump_product_popularity,
    bump_products_on_order_completed,
)


async def seller_snapshot(store_name: str) -> dict | None:
    reg = await get_registrations_collection().find_one({"store_name": store_name})
    if not reg:
        return None
    seller_id = str(reg["_id"])
    product = await get_catalog_products_collection().find_one(
        {"seller_id": seller_id, "view_only": {"$ne": True}},
    )
    return {
        "name": store_name,
        "plan": reg.get("plan_tier"),
        "multiplier": recommendation_multiplier(reg),
        "product": product,
    }


async def verify_bump(product: dict, multiplier: int, event: str) -> tuple[bool, str]:
    product_id = product["_id"]
    before = int(product.get("popularity") or 0)
    if event == "purchase":
        await bump_products_on_order_completed([{"product_id": str(product_id)}])
        base = POPULARITY_DELTA["purchase"]
    else:
        await bump_product_popularity(str(product_id), event)
        base = POPULARITY_DELTA[event]

    after_doc = await get_catalog_products_collection().find_one({"_id": product_id})
    after = int(after_doc.get("popularity") or 0)
    delta = after - before
    expected = base * multiplier
    ok = delta == expected
    return ok, f"delta={delta}, esperado={expected}"


async def main() -> None:
    await connect_to_mongo()

    print(f"PREMIUM_RECOMMENDATION_MULTIPLIER = {PREMIUM_RECOMMENDATION_MULTIPLIER}")
    print(f"POPULARITY_DELTA = {POPULARITY_DELTA}\n")

    premium = await seller_snapshot("Tienducha")
    standard = await seller_snapshot("Mercado Centro")

    for snapshot in (premium, standard):
        if snapshot is None:
            continue
        boost = "SI" if snapshot["multiplier"] == PREMIUM_RECOMMENDATION_MULTIPLIER else "NO"
        print(
            f"{snapshot['name']}: plan={snapshot['plan']}, "
            f"multiplier={snapshot['multiplier']}, boost={boost}"
        )

    all_ok = True

    if premium and premium["product"]:
        print("\n--- Tienducha (Premium) ---")
        for event in ("view", "jaba", "purchase"):
            ok, detail = await verify_bump(premium["product"], premium["multiplier"], event)
            status = "OK" if ok else "FAIL"
            print(f"  {event}: {status} ({detail})")
            all_ok = all_ok and ok
            premium["product"] = await get_catalog_products_collection().find_one(
                {"_id": premium["product"]["_id"]},
            )

    if standard and standard["product"]:
        print("\n--- Mercado Centro (Standard) ---")
        ok, detail = await verify_bump(standard["product"], standard["multiplier"], "view")
        status = "OK" if ok else "FAIL"
        print(f"  view: {status} ({detail})")
        all_ok = all_ok and ok

    print("\nRESULTADO:", "TODO OK" if all_ok else "HAY FALLOS")
    await close_mongo_connection()
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
