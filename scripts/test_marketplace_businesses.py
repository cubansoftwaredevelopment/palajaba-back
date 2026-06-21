"""
Prueba de integración: GET /api/marketplace/businesses

Levanta el backend si la ruta no está disponible (código viejo en :8081),
siembra tiendas y vistas de perfil en Mongo, verifica visibilidad y orden
por popularidad, y limpia los datos de prueba.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_marketplace_businesses.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from bson import ObjectId

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_catalog_products_collection,
    get_registrations_collection,
    get_seller_profile_views_collection,
)
from app.utils.datetime import to_utc_naive, utc_now

MARKER = "marketplace_businesses_integration_v1"
PROVINCE_ID = "la-habana"
LOCAL_MUNICIPALITY_ID = "playa"
REMOTE_MUNICIPALITY_ID = "marianao"
HIDDEN_MUNICIPALITY_ID = "matanzas"

BASE_URL = "http://127.0.0.1:8081"
HEALTH_URL = f"{BASE_URL}/api/health"
BUSINESSES_URL = f"{BASE_URL}/api/marketplace/businesses"
BACKEND_PROC: subprocess.Popen | None = None
TEST_PORT = 8081


def set_base_url(port: int) -> None:
    global BASE_URL, HEALTH_URL, BUSINESSES_URL, TEST_PORT
    TEST_PORT = port
    BASE_URL = f"http://127.0.0.1:{port}"
    HEALTH_URL = f"{BASE_URL}/api/health"
    BUSINESSES_URL = f"{BASE_URL}/api/marketplace/businesses"


def http_json(method: str, url: str, *, body: dict | None = None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wait_for_backend(max_seconds: int = 60) -> None:
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("El backend no respondió a tiempo en /api/health")


def businesses_route_exists() -> bool:
    status, _ = http_json("GET", BUSINESSES_URL)
    return status != 404


def ensure_backend_running() -> subprocess.Popen | None:
    global BACKEND_PROC

    for port in (8081, 8082):
        set_base_url(port)
        try:
            wait_for_backend(max_seconds=3)
        except RuntimeError:
            continue
        if businesses_route_exists():
            print(f"Backend con ruta /businesses en :{port}")
            return None

    set_base_url(8082)
    print("Levantando backend de prueba en :8082 (código actual)…")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    python_exe = BACKEND_ROOT / "venv" / "Scripts" / "python.exe"
    BACKEND_PROC = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8082",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_backend(max_seconds=60)
    assert_ok(businesses_route_exists(), "El backend levantado no expone /api/marketplace/businesses")
    print("Backend listo en :8082.")
    return BACKEND_PROC


def stop_backend(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    print("Deteniendo backend de prueba…")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def unique_phone() -> str:
    return f"{int(uuid.uuid4().hex[:8], 16) % 100000000:08d}"


def seller_base(*, store_name: str, store_slug: str, municipality_id: str, municipality_name: str, transfer_id: str) -> dict:
    now = to_utc_naive(utc_now())
    return {
        "status": "approved",
        "transfer_id": transfer_id,
        "store_name": store_name,
        "store_slug": store_slug,
        "phone": unique_phone(),
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": True,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": municipality_id,
            "municipality_name": municipality_name,
        },
        "delivery_areas": [],
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=27),
        MARKER: True,
    }


async def cleanup_test_data() -> None:
    registrations = get_registrations_collection()
    products = get_catalog_products_collection()
    views = get_seller_profile_views_collection()
    sellers = await registrations.find({MARKER: True}, {"_id": 1}).to_list(length=None)
    seller_ids = [str(doc["_id"]) for doc in sellers]
    if seller_ids:
        await views.delete_many({"seller_id": {"$in": seller_ids}})
        await products.delete_many({"seller_id": {"$in": seller_ids}})
    await registrations.delete_many({MARKER: True})


async def seed_catalog_product(
    seller_id: str,
    *,
    name: str,
    view_only: bool = False,
) -> None:
    products = get_catalog_products_collection()
    now = to_utc_naive(utc_now())
    await products.insert_one(
        {
            "seller_id": seller_id,
            "category_id": ObjectId(),
            "name": name,
            "description": "Producto de prueba negocios",
            "image_url": "https://example.com/product.jpg",
            "base_price": 100.0,
            "base_currency": "CUP",
            "accepted_currencies": ["CUP"],
            "offers_delivery": True,
            "is_available": True,
            "view_only": view_only,
            "global_category_id": "food",
            MARKER: True,
            "created_at": now,
            "updated_at": now,
        }
    )


async def seed_profile_views(seller_id: str, count: int) -> None:
    views = get_seller_profile_views_collection()
    now = to_utc_naive(utc_now())
    docs = [{"seller_id": seller_id, "viewed_at": now} for _ in range(count)]
    if docs:
        await views.insert_many(docs)


async def seed_test_sellers() -> dict[str, str]:
    registrations = get_registrations_collection()
    await cleanup_test_data()

    popular_oid = ObjectId()
    delivery_oid = ObjectId()
    less_popular_oid = ObjectId()
    pickup_oid = ObjectId()
    empty_oid = ObjectId()
    hidden_oid = ObjectId()
    incomplete_oid = ObjectId()

    docs = [
        (
            popular_oid,
            {
                **seller_base(
                    store_name=f"TEST Popular Negocios {MARKER}",
                    store_slug="test-popular-negocios",
                    municipality_id=LOCAL_MUNICIPALITY_ID,
                    municipality_name="Playa",
                    transfer_id=f"TEST-BIZ-POP-{MARKER}",
                ),
                "category_ids": ["food"],
            },
            8,
        ),
        (
            delivery_oid,
            {
                **seller_base(
                    store_name=f"TEST Delivery Negocios {MARKER}",
                    store_slug="test-delivery-negocios",
                    municipality_id=REMOTE_MUNICIPALITY_ID,
                    municipality_name="Marianao",
                    transfer_id=f"TEST-BIZ-DEL-{MARKER}",
                ),
                "delivery_areas": [
                    {
                        "province_id": PROVINCE_ID,
                        "province_name": "La Habana",
                        "municipality_id": LOCAL_MUNICIPALITY_ID,
                        "municipality_name": "Playa",
                    }
                ],
            },
            5,
        ),
        (
            less_popular_oid,
            seller_base(
                store_name=f"TEST Menos Popular Negocios {MARKER}",
                store_slug="test-menos-popular-negocios",
                municipality_id=LOCAL_MUNICIPALITY_ID,
                municipality_name="Playa",
                transfer_id=f"TEST-BIZ-LESS-{MARKER}",
            ),
            2,
        ),
        (
            pickup_oid,
            {
                **seller_base(
                    store_name=f"TEST Pickup Negocios {MARKER}",
                    store_slug="test-pickup-negocios",
                    municipality_id=REMOTE_MUNICIPALITY_ID,
                    municipality_name="Marianao",
                    transfer_id=f"TEST-BIZ-PICK-{MARKER}",
                ),
                "offers_delivery": False,
                "delivery_areas": [],
                "category_ids": ["construccion"],
            },
            3,
        ),
        (
            empty_oid,
            seller_base(
                store_name=f"TEST Vacio Negocios {MARKER}",
                store_slug="test-vacio-negocios",
                municipality_id=LOCAL_MUNICIPALITY_ID,
                municipality_name="Playa",
                transfer_id=f"TEST-BIZ-EMPTY-{MARKER}",
            ),
            20,
        ),
        (
            hidden_oid,
            {
                **seller_base(
                    store_name=f"TEST Oculto Negocios {MARKER}",
                    store_slug="test-oculto-negocios",
                    municipality_id=HIDDEN_MUNICIPALITY_ID,
                    municipality_name="Matanzas",
                    transfer_id=f"TEST-BIZ-HID-{MARKER}",
                ),
                "business_area": {
                    "province_id": "matanzas",
                    "province_name": "Matanzas",
                    "municipality_id": HIDDEN_MUNICIPALITY_ID,
                    "municipality_name": "Matanzas",
                },
                "offers_delivery": False,
            },
            99,
        ),
        (
            incomplete_oid,
            {
                **seller_base(
                    store_name=f"TEST Incompleto Negocios {MARKER}",
                    store_slug="test-incompleto-negocios",
                    municipality_id=LOCAL_MUNICIPALITY_ID,
                    municipality_name="Playa",
                    transfer_id=f"TEST-BIZ-INC-{MARKER}",
                ),
                "profile_photo_url": None,
            },
            50,
        ),
    ]

    for oid, doc, view_count in docs:
        await registrations.insert_one({**doc, "_id": oid})
        await seed_profile_views(str(oid), view_count)

    product_plan = {
        str(popular_oid): ("Producto popular", False),
        str(delivery_oid): ("Producto delivery", False),
        str(less_popular_oid): ("Producto menos popular", False),
        str(pickup_oid): ("Producto pickup", True),
        str(empty_oid): None,
        str(hidden_oid): ("Producto oculto", False),
        str(incomplete_oid): ("Producto incompleto", False),
    }
    for seller_id, product_info in product_plan.items():
        if product_info is None:
            continue
        name, view_only = product_info
        await seed_catalog_product(seller_id, name=name, view_only=view_only)

    return {
        "popular_id": str(popular_oid),
        "delivery_id": str(delivery_oid),
        "less_popular_id": str(less_popular_oid),
        "pickup_id": str(pickup_oid),
        "empty_id": str(empty_oid),
        "hidden_id": str(hidden_oid),
        "incomplete_id": str(incomplete_oid),
    }


def fetch_businesses(
    *,
    limit: int = 20,
    offset: int = 0,
    query: str = "",
    category_id: str | None = None,
    additional_municipality_ids: list[str] | None = None,
):
    params: list[tuple[str, str]] = [
        ("province_id", PROVINCE_ID),
        ("municipality_id", LOCAL_MUNICIPALITY_ID),
        ("limit", str(limit)),
        ("offset", str(offset)),
    ]
    if query.strip():
        params.append(("q", query.strip()))
    if category_id:
        params.append(("category_id", category_id))
    for municipality_id in additional_municipality_ids or []:
        params.append(("municipios_adicionales", municipality_id))
    query_string = urllib.parse.urlencode(params)
    return http_json("GET", f"{BUSINESSES_URL}?{query_string}")


async def run_tests() -> None:
    if not os.getenv("MONGODB_URL", "").strip():
        raise RuntimeError("MONGODB_URL no configurada")

    await connect_to_mongo()
    seeded = await seed_test_sellers()

    try:
        print("1. GET /api/marketplace/businesses debe responder 200…")
        status, payload = fetch_businesses()
        assert_ok(status == 200, f"GET businesses falló ({status}): {payload}")
        assert_ok(isinstance(payload.get("businesses"), list), "Falta lista businesses")
        print("   OK respuesta 200")

        print("2. Visibilidad: local + domicilio sí; remoto sin domicilio e incompleto no…")
        returned_ids = {item["store"]["id"] for item in payload["businesses"]}
        assert_ok(seeded["popular_id"] in returned_ids, "Falta tienda local popular")
        assert_ok(seeded["delivery_id"] in returned_ids, "Falta tienda con domicilio a Playa")
        assert_ok(seeded["less_popular_id"] in returned_ids, "Falta tienda local menos popular")
        assert_ok(seeded["empty_id"] not in returned_ids, "No debe aparecer tienda sin productos")
        assert_ok(seeded["hidden_id"] not in returned_ids, "No debe aparecer tienda fuera de zona")
        assert_ok(seeded["incomplete_id"] not in returned_ids, "No debe aparecer tienda incompleta")
        print("   OK visibilidad correcta")

        print("3. Orden por popularidad descendente…")
        test_rows = [
            item
            for item in payload["businesses"]
            if item["store"]["id"] in {
                seeded["popular_id"],
                seeded["delivery_id"],
                seeded["less_popular_id"],
            }
        ]
        assert_ok(len(test_rows) == 3, f"Se esperaban 3 tiendas de prueba visibles, hubo {len(test_rows)}")
        names = [row["store"]["store_name"] for row in test_rows]
        popularities = [row["popularity"] for row in test_rows]
        assert_ok(
            popularities == sorted(popularities, reverse=True),
            f"Popularidad no está ordenada: {popularities}",
        )
        assert_ok(
            names[0].startswith("TEST Popular"),
            f"La más popular debería ir primero, orden actual: {names}",
        )
        print(f"   OK orden: {popularities}")

        print("4. Paginación…")
        status, page = fetch_businesses(limit=2, offset=0)
        assert_ok(status == 200, f"GET paginado falló ({status}): {page}")
        assert_ok(len(page["businesses"]) == 2, "limit=2 debe devolver 2 negocios")
        assert_ok(page["has_more"] is True, "Debe indicar has_more=true")
        assert_ok(page["total_businesses"] >= 3, "total_businesses debe incluir las tiendas de prueba")

        status, page2 = fetch_businesses(limit=2, offset=2)
        assert_ok(status == 200, f"GET offset falló ({status}): {page2}")
        page1_ids = {item["store"]["id"] for item in page["businesses"]}
        page2_ids = {item["store"]["id"] for item in page2["businesses"]}
        assert_ok(not page1_ids.intersection(page2_ids), "Las páginas no deben repetir negocios")
        print("   OK paginación")

        print("5. Servicio directo alineado con API…")
        from app.services.marketplace import list_businesses

        service_result = await list_businesses(
            PROVINCE_ID,
            LOCAL_MUNICIPALITY_ID,
            limit=50,
            offset=0,
        )
        service_test_ids = {
            business.store.id
            for business in service_result.businesses
            if business.store.id
            in {
                seeded["popular_id"],
                seeded["delivery_id"],
                seeded["less_popular_id"],
            }
        }
        assert_ok(
            service_test_ids == {
                seeded["popular_id"],
                seeded["delivery_id"],
                seeded["less_popular_id"],
            },
            "El servicio debe exponer las mismas tiendas visibles de prueba",
        )
        print("   OK servicio alineado con API")

        print("7. Municipio adicional para recogida muestra aviso sin domicilio…")
        status, without_extra = fetch_businesses()
        without_extra_ids = {item["store"]["id"] for item in without_extra["businesses"]}
        assert_ok(seeded["pickup_id"] not in without_extra_ids, "Pickup no debe aparecer sin municipio adicional")

        status, with_extra = fetch_businesses(additional_municipality_ids=[REMOTE_MUNICIPALITY_ID])
        assert_ok(status == 200, f"GET con municipio adicional falló ({status}): {with_extra}")
        pickup_row = next(
            (item for item in with_extra["businesses"] if item["store"]["id"] == seeded["pickup_id"]),
            None,
        )
        assert_ok(pickup_row is not None, "Pickup debe aparecer con municipio adicional")
        assert_ok(pickup_row["pickup_required"] is True, "Pickup debe requerir recogida")
        assert_ok(
            "Recoger en Marianao" in (pickup_row.get("pickup_notice") or ""),
            f"Aviso pickup inesperado: {pickup_row.get('pickup_notice')}",
        )
        print("   OK pickup con aviso sin domicilio")

        print("8. Búsqueda por nombre…")
        status, search_payload = fetch_businesses(query="Delivery Negocios")
        assert_ok(status == 200, f"Búsqueda falló ({status}): {search_payload}")
        search_ids = {item["store"]["id"] for item in search_payload["businesses"]}
        assert_ok(seeded["delivery_id"] in search_ids, "Búsqueda debe encontrar tienda delivery")
        assert_ok(seeded["popular_id"] not in search_ids, "Búsqueda no debe incluir tiendas irrelevantes")
        print("   OK búsqueda")

        print("9. Filtro por categoría…")
        status, food_payload = fetch_businesses(category_id="food")
        assert_ok(status == 200, f"Filtro food falló ({status}): {food_payload}")
        food_ids = {item["store"]["id"] for item in food_payload["businesses"]}
        assert_ok(seeded["popular_id"] in food_ids, "Popular food debe filtrarse por categoría")

        status, category_with_extra = fetch_businesses(
            category_id="construccion",
            additional_municipality_ids=[REMOTE_MUNICIPALITY_ID],
        )
        assert_ok(status == 200, f"Filtro construcción falló ({status}): {category_with_extra}")
        category_with_extra_ids = {item["store"]["id"] for item in category_with_extra["businesses"]}
        assert_ok(seeded["pickup_id"] in category_with_extra_ids, "Pickup construcción debe filtrarse")
        print("   OK filtro categoría")

        print("10. Query corta sin categoría debe fallar…")
        status, short_query = fetch_businesses(query="a")
        assert_ok(status == 400, f"Query corta debía fallar con 400, respondió {status}: {short_query}")
        print(f"   OK validación query -> {status}")

    finally:
        print("11. Limpiar datos de prueba…")
        await cleanup_test_data()
        print("   OK cleanup")


async def main() -> None:
    proc = None
    try:
        proc = ensure_backend_running()
        print("Ejecutando pruebas de integración contra API real…")
        await run_tests()
        print("\n[OK] Todas las pruebas de integración pasaron.")
    finally:
        await close_mongo_connection()
        stop_backend(proc)


if __name__ == "__main__":
    asyncio.run(main())
