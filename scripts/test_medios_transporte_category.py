"""
Prueba de integración amplia: categoría global «Medios de transporte».

Verifica seed en Mongo, API pública, perfil de vendedor, catálogo, marketplace
y aliases legacy (vehiculos-repuestos, transporte).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_medios_transporte_category.py
"""
from __future__ import annotations

import asyncio
import io
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
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.config import settings
from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_admins_collection,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_categories_collection,
    get_registrations_collection,
)
from app.schemas.seller_profile import BusinessArea, SellerProfileUpdate
from app.security import create_admin_token
from app.services import catalog as catalog_service
from app.services import categories as categories_service
from app.services import marketplace as marketplace_service
from app.services import seller_profile as seller_profile_service
from app.utils.datetime import to_utc_naive, utc_now

BASE_URL = "http://127.0.0.1:8081"
HEALTH_URL = f"{BASE_URL}/api/health"
BACKEND_PROC: subprocess.Popen | None = None
CATEGORY_ID = "medios-transporte"
CATEGORY_NAME = "Medios de transporte"
PROVINCE_ID = "la-habana"
MUNICIPALITY_ID = "playa"

MINI_PNG = bytes(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


def http_json(method: str, url: str, *, token: str | None = None, body: dict | None = None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

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


def category_route_exists() -> bool:
    status, payload = http_json("GET", f"{BASE_URL}/api/categories/")
    if status != 200 or not isinstance(payload, list):
        return False
    return any(item.get("id") == CATEGORY_ID for item in payload)


def ensure_backend_running() -> subprocess.Popen | None:
    global BACKEND_PROC, BASE_URL, HEALTH_URL

    for port in (8081, 8082):
        BASE_URL = f"http://127.0.0.1:{port}"
        HEALTH_URL = f"{BASE_URL}/api/health"
        try:
            wait_for_backend(max_seconds=3)
        except RuntimeError:
            continue
        if category_route_exists():
            print(f"Backend con categorías actualizadas en :{port}")
            return None

    BASE_URL = "http://127.0.0.1:8082"
    HEALTH_URL = f"{BASE_URL}/api/health"
    print("Levantando backend de prueba en :8082…")
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
    assert_ok(category_route_exists(), "El backend no expone la categoría medios-transporte")
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


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def unique_phone() -> str:
    return f"{int(unique_suffix(), 16) % 100000000:08d}"


async def get_admin_token() -> str:
    admin = await get_admins_collection().find_one(
        {"username": settings.admin_username, "is_active": True}
    )
    assert_ok(admin is not None, f"Admin «{settings.admin_username}» no existe")
    return create_admin_token(username=admin["username"], admin_id=str(admin["_id"]))


async def register_and_approve(admin_token: str, suffix: str) -> tuple[str, str, str, str]:
    transfer_id = f"TEST-TRANS-{suffix}"
    store_name = f"Transporte Test {suffix}"
    phone = unique_phone()
    password = "TestTransport2026!"

    status, payload = http_json(
        "POST",
        f"{BASE_URL}/api/register",
        body={
            "transfer_id": transfer_id,
            "store_name": store_name,
            "phone": phone,
            "password": password,
            "billing_period": "monthly",
            "plan_tier": "standard",
        },
    )
    assert_ok(status == 201, f"Registro falló ({status}): {payload}")
    seller_id = payload["id"]

    approve_params = urllib.parse.urlencode(
        {
            "payment_amount_cup": "2",
            "subscription_ends_at": (to_utc_naive(utc_now()) + timedelta(days=30)).strftime("%Y-%m-%d"),
        }
    )
    status, approved = http_json(
        "POST",
        f"{BASE_URL}/api/admin/registrations/{seller_id}/approve?{approve_params}",
        token=admin_token,
    )
    assert_ok(status == 200, f"Aprobar falló ({status}): {approved}")
    return seller_id, store_name, phone, password


async def complete_seller_profile(seller_id: str) -> None:
    now = to_utc_naive(utc_now())
    await get_registrations_collection().update_one(
        {"_id": ObjectId(seller_id)},
        {
            "$set": {
                "profile_photo_url": "https://example.com/test-transporte-profile.jpg",
                "offers_delivery": False,
                "category_ids": [CATEGORY_ID],
                "business_area": {
                    "province_id": PROVINCE_ID,
                    "province_name": "La Habana",
                    "municipality_id": MUNICIPALITY_ID,
                    "municipality_name": "Playa",
                },
                "profile_completed_at": now,
                "updated_at": now,
            }
        },
    )


def seller_login(phone: str, password: str) -> str:
    status, payload = http_json(
        "POST",
        f"{BASE_URL}/api/auth/login",
        body={"method": "phone", "phone": phone, "password": password},
    )
    assert_ok(status == 200, f"Login vendedor falló ({status}): {payload}")
    return payload["access_token"]


async def delete_registration(admin_token: str, registration_id: str) -> None:
    status, payload = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{registration_id}",
        token=admin_token,
    )
    assert_ok(status == 200, f"DELETE cleanup falló ({status}): {payload}")


def upload_file(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


async def run_tests() -> None:
    await connect_to_mongo()
    admin_token = await get_admin_token()
    suffix = unique_suffix()
    seller_id: str | None = None

    try:
        print("1. Seed y catálogo canónico de categorías…")
        await categories_service.ensure_category_seed()
        mongo_doc = await get_categories_collection().find_one({"id": CATEGORY_ID})
        assert_ok(mongo_doc is not None, "Mongo no tiene medios-transporte tras el seed")
        assert_ok(mongo_doc["name"] == CATEGORY_NAME, "Nombre en Mongo incorrecto")
        listed = await categories_service.list_categories()
        assert_ok(any(item.id == CATEGORY_ID for item in listed), "list_categories omite medios-transporte")
        print("   OK seed")

        print("2. API pública GET /api/categories…")
        status, categories = http_json("GET", f"{BASE_URL}/api/categories/")
        assert_ok(status == 200, f"GET categories falló ({status}): {categories}")
        match = next((item for item in categories if item["id"] == CATEGORY_ID), None)
        assert_ok(match is not None, "La API pública no devuelve medios-transporte")
        assert_ok(match["name"] == CATEGORY_NAME, "Nombre en API público incorrecto")
        print("   OK API pública")

        print("3. Validación de IDs y aliases en servicio…")
        await categories_service.validate_category_ids([CATEGORY_ID, "servicios"])
        known_ids = {item["id"] for item in categories_service.DEFAULT_CATEGORIES}
        assert_ok(CATEGORY_ID in known_ids, "medios-transporte debe estar en DEFAULT_CATEGORIES")
        assert_ok(
            categories_service.normalize_business_category_id("vehiculos-repuestos") == CATEGORY_ID,
            "Alias vehiculos-repuestos no mapea a medios-transporte",
        )
        assert_ok(
            categories_service.normalize_business_category_id("transporte") == CATEGORY_ID,
            "Alias transporte no mapea a medios-transporte",
        )
        assert_ok(
            categories_service.normalize_business_category_id("categoria-desconocida-xyz") == "otros",
            "IDs desconocidos deben seguir normalizando a otros",
        )
        print("   OK validación y aliases")

        print("4. Tienda de prueba con categoría Medios de transporte…")
        seller_id, store_name, phone, password = await register_and_approve(admin_token, suffix)
        await complete_seller_profile(seller_id)
        seller_token = seller_login(phone, password)

        status, business_categories = http_json(
            "GET",
            f"{BASE_URL}/api/auth/me/business-categories",
            token=seller_token,
        )
        assert_ok(status == 200, f"GET business-categories falló ({status}): {business_categories}")
        assert_ok(
            any(item["id"] == CATEGORY_ID for item in business_categories),
            "business-categories no incluye medios-transporte",
        )
        print("   OK tienda y business-categories")

        print("5. PATCH perfil vía API con medios-transporte…")
        profile_payload = SellerProfileUpdate(
            business_area=BusinessArea(
                province_id=PROVINCE_ID,
                province_name="La Habana",
                municipality_id=MUNICIPALITY_ID,
                municipality_name="Playa",
            ),
            category_ids=[CATEGORY_ID, "servicios"],
            offers_delivery=False,
            biography="Venta de bicicletas y repuestos.",
        )
        updated = await seller_profile_service.update_seller_profile(seller_id, profile_payload)
        assert_ok(CATEGORY_ID in updated.category_ids, "Perfil no guardó medios-transporte")
        assert_ok(updated.profile_completed, "Perfil debería quedar completo")
        print("   OK perfil")

        print("6. Catálogo: categoría local y producto global medios-transporte…")
        status, local_category = http_json(
            "POST",
            f"{BASE_URL}/api/auth/me/catalog/categories",
            token=seller_token,
            body={"name": "Bicicletas"},
        )
        assert_ok(status == 201, f"Crear categoría local falló ({status}): {local_category}")
        local_category_id = local_category["id"]

        product = await catalog_service.create_catalog_product(
            seller_id,
            name="Bici de prueba",
            description="Producto de integración",
            base_price=1500.0,
            base_currency="CUP",
            accepted_currencies_raw="[]",
            category_id=local_category_id,
            global_category_id=CATEGORY_ID,
            offers_delivery=False,
            view_only=False,
            is_available=True,
            photo=upload_file(MINI_PNG, "test-bici.png", "image/png"),
        )
        assert_ok(product.global_category_id == CATEGORY_ID, "Producto no guardó global_category_id correcto")
        assert_ok(product.global_category_name == CATEGORY_NAME, "Nombre global del producto incorrecto")

        rejected_product = False
        try:
            await catalog_service.create_catalog_product(
                seller_id,
                name="Producto inválido",
                description=None,
                base_price=100.0,
                base_currency="CUP",
                accepted_currencies_raw="[]",
                category_id=local_category_id,
                global_category_id="moda",
                offers_delivery=False,
                view_only=False,
                is_available=True,
                photo=upload_file(MINI_PNG, "test-invalid.png", "image/png"),
            )
        except Exception:
            rejected_product = True
        assert_ok(rejected_product, "Debió rechazar global_category_id fuera del perfil")
        print("   OK catálogo")

        print("7. Marketplace feed y filtro por categoría…")
        feed = await marketplace_service.list_home_feed(
            PROVINCE_ID,
            MUNICIPALITY_ID,
            limit_per_category=20,
        )
        section = next((item for item in feed.sections if item.category_id == CATEGORY_ID), None)
        assert_ok(section is not None, "Feed no incluye sección medios-transporte")
        assert_ok(section.category_name == CATEGORY_NAME, "Nombre de sección incorrecto en feed")
        assert_ok(len(section.products) >= 1, "Sección sin productos")

        by_id = await marketplace_service.list_category_products(
            PROVINCE_ID,
            MUNICIPALITY_ID,
            CATEGORY_ID,
            limit=20,
            offset=0,
        )
        assert_ok(by_id.category_id == CATEGORY_ID, "list_category_products id incorrecto")
        assert_ok(len(by_id.products) >= 1, "list_category_products sin resultados")

        by_alias = await marketplace_service.list_category_products(
            PROVINCE_ID,
            MUNICIPALITY_ID,
            "vehiculos-repuestos",
            limit=20,
            offset=0,
        )
        assert_ok(by_alias.category_id == CATEGORY_ID, "Alias vehiculos-repuestos no resuelve en marketplace")
        assert_ok(len(by_alias.products) >= 1, "Alias vehiculos-repuestos no devuelve productos")

        search = await marketplace_service.search_products(
            PROVINCE_ID,
            MUNICIPALITY_ID,
            query="Bici",
            global_category_id=CATEGORY_ID,
            limit=20,
            offset=0,
        )
        assert_ok(search.category_id == CATEGORY_ID, "Búsqueda con filtro de categoría incorrecta")
        assert_ok(len(search.products) >= 1, "Búsqueda no encontró el producto de prueba")
        print("   OK marketplace")

        print("8. Mapeo de categoria local legacy a medios-transporte…")
        from app.services.product_categories import map_local_category_name_to_business_category

        assert_ok(map_local_category_name_to_business_category("Transporte") == CATEGORY_ID, "Mapeo local falló")
        assert_ok(map_local_category_name_to_business_category("Vehículos") == CATEGORY_ID, "Mapeo vehículos falló")
        print("   OK mapeo local")

        print(f"9. Limpieza de tienda «{store_name}»…")
        await delete_registration(admin_token, seller_id)
        seller_id = None
        print("   OK cleanup")

    finally:
        if seller_id:
            try:
                await delete_registration(admin_token, seller_id)
            except AssertionError as exc:
                print(f"   AVISO cleanup: {exc}")
            await get_catalog_products_collection().delete_many({"seller_id": seller_id})
            await get_catalog_categories_collection().delete_many({"seller_id": seller_id})


async def main() -> None:
    proc = None
    try:
        proc = ensure_backend_running()
        print("Ejecutando pruebas de integración de Medios de transporte…")
        await run_tests()
        print("\n[OK] Todas las pruebas de integración pasaron.")
    finally:
        await close_mongo_connection()
        stop_backend(proc)


if __name__ == "__main__":
    asyncio.run(main())
