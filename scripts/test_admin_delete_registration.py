"""
Prueba de integración: eliminar tiendas desde el panel admin (API + MongoDB).

Levanta el backend si no está en marcha, ejecuta DELETE real y verifica la cascada.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_admin_delete_registration.py
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

from app.config import settings
from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_admins_collection,
    get_catalog_categories_collection,
    get_catalog_products_collection,
    get_notifications_collection,
    get_orders_collection,
    get_registrations_collection,
    get_seller_profile_views_collection,
)
from app.security import create_admin_token
from app.utils.datetime import to_utc_naive, utc_now

BASE_URL = "http://127.0.0.1:8081"
HEALTH_URL = f"{BASE_URL}/api/health"
BACKEND_PROC: subprocess.Popen | None = None


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


def ensure_backend_running() -> subprocess.Popen | None:
    global BACKEND_PROC
    try:
        wait_for_backend(max_seconds=3)
        print("Backend ya estaba en marcha en :8081")
        return None
    except RuntimeError:
        pass

    print("Levantando backend en :8081…")
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
            "8081",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_backend(max_seconds=60)
    print("Backend listo.")
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
    await connect_to_mongo()
    admin = await get_admins_collection().find_one(
        {"username": settings.admin_username, "is_active": True}
    )
    assert_ok(admin is not None, f"Admin «{settings.admin_username}» no existe en la base de datos")
    return create_admin_token(
        username=admin["username"],
        admin_id=str(admin["_id"]),
    )


async def register_test_store(*, suffix: str) -> tuple[str, str, str]:
    transfer_id = f"TEST-DEL-{suffix}"
    store_name = f"Tienda Delete Test {suffix}"
    phone = unique_phone()
    password = "TestDelete2026!"

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
    return payload["id"], store_name, phone


async def approve_registration(admin_token: str, registration_id: str) -> None:
    approve_params = urllib.parse.urlencode(
        {
            "payment_amount_cup": "2",
            "subscription_ends_at": (to_utc_naive(utc_now()) + timedelta(days=30)).strftime("%Y-%m-%d"),
        }
    )
    status, approved = http_json(
        "POST",
        f"{BASE_URL}/api/admin/registrations/{registration_id}/approve?{approve_params}",
        token=admin_token,
    )
    assert_ok(status == 200, f"Aprobar falló ({status}): {approved}")
    assert_ok(approved["status"] == "approved", "Estado tras aprobar debe ser approved")


async def seed_related_data(seller_id: str, store_name: str) -> None:
    now = to_utc_naive(utc_now())
    seller_oid = ObjectId(seller_id)

    category_id = (
        await get_catalog_categories_collection().insert_one(
            {
                "seller_id": seller_id,
                "name": "Categoría test delete",
                "sort_order": 0,
                "product_count": 1,
                "created_at": now,
                "updated_at": now,
            }
        )
    ).inserted_id

    await get_catalog_products_collection().insert_one(
        {
            "seller_id": seller_id,
            "category_id": category_id,
            "global_category_id": "otros",
            "name": "Producto test delete",
            "description": "Para prueba de cascada",
            "image_url": "https://example.com/test-delete-product.jpg",
            "base_price": 100.0,
            "base_currency": "CUP",
            "accepted_currencies": [],
            "offers_delivery": False,
            "view_only": False,
            "is_available": True,
            "sort_order": 0,
            "popularity": 0,
            "created_at": now,
            "updated_at": now,
        }
    )

    await get_orders_collection().insert_one(
        {
            "seller_id": seller_id,
            "store_name": store_name,
            "status": "pending_confirmation",
            "items": [
                {
                    "product_id": str(ObjectId()),
                    "name": "Item test",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "currency": "CUP",
                    "line_total": 100.0,
                }
            ],
            "subtotals": [{"currency": "CUP", "amount": 100.0}],
            "delivery_requested": False,
            "delivery": None,
            "delivery_price": None,
            "delivery_currency": None,
            "payment_currency": "CUP",
            "buyer_zone": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
    )

    await get_notifications_collection().insert_one(
        {
            "seller_id": seller_oid,
            "title": "Notificación test delete",
            "content": "Prueba de cascada",
            "created_at": now,
            "read_at": None,
        }
    )

    await get_seller_profile_views_collection().insert_one(
        {"seller_id": seller_id, "viewed_at": now},
    )


async def assert_seller_data_gone(seller_id: str) -> None:
    seller_oid = ObjectId(seller_id)
    assert_ok(
        await get_registrations_collection().count_documents({"_id": seller_oid}) == 0,
        "El registro de la tienda sigue en registrations",
    )
    assert_ok(
        await get_catalog_products_collection().count_documents({"seller_id": seller_id}) == 0,
        "Quedaron productos del vendedor",
    )
    assert_ok(
        await get_catalog_categories_collection().count_documents({"seller_id": seller_id}) == 0,
        "Quedaron categorías del vendedor",
    )
    assert_ok(
        await get_orders_collection().count_documents({"seller_id": seller_id}) == 0,
        "Quedaron pedidos del vendedor",
    )
    assert_ok(
        await get_notifications_collection().count_documents({"seller_id": seller_oid}) == 0,
        "Quedaron notificaciones del vendedor",
    )
    assert_ok(
        await get_seller_profile_views_collection().count_documents({"seller_id": seller_id}) == 0,
        "Quedaron vistas de perfil del vendedor",
    )


async def assert_related_data_exists(seller_id: str) -> None:
    seller_oid = ObjectId(seller_id)
    assert_ok(
        await get_catalog_products_collection().count_documents({"seller_id": seller_id}) > 0,
        "No se sembró producto de prueba",
    )
    assert_ok(
        await get_orders_collection().count_documents({"seller_id": seller_id}) > 0,
        "No se sembró pedido de prueba",
    )
    assert_ok(
        await get_notifications_collection().count_documents({"seller_id": seller_oid}) > 0,
        "No se sembró notificación de prueba",
    )


async def run_tests() -> None:
    admin_token = await get_admin_token()
    print("   OK token admin")

    print("1. Eliminar solicitud pendiente vía API…")
    pending_id, pending_name, _ = await register_test_store(suffix=f"pend-{unique_suffix()}")
    status, deleted = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{pending_id}",
        token=admin_token,
    )
    assert_ok(status == 200, f"DELETE pendiente falló ({status}): {deleted}")
    assert_ok(deleted["id"] == pending_id, "ID devuelto no coincide")
    assert_ok(deleted["store_name"] == pending_name, "Nombre devuelto no coincide")
    assert_ok("eliminada" in deleted["message"].lower(), "Mensaje de éxito inesperado")

    status, missing = http_json(
        "GET",
        f"{BASE_URL}/api/admin/registrations/{pending_id}",
        token=admin_token,
    )
    assert_ok(status == 404, f"GET tras borrar debe ser 404, fue {status}: {missing}")
    await assert_seller_data_gone(pending_id)
    print("   OK pendiente eliminada")

    print("2. Eliminar tienda aprobada con catálogo, pedidos y notificaciones…")
    approved_id, approved_name, _ = await register_test_store(suffix=f"appr-{unique_suffix()}")
    await approve_registration(admin_token, approved_id)
    await seed_related_data(approved_id, approved_name)
    await assert_related_data_exists(approved_id)

    status, deleted = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{approved_id}",
        token=admin_token,
    )
    assert_ok(status == 200, f"DELETE aprobada falló ({status}): {deleted}")
    assert_ok(deleted["store_name"] == approved_name, "Nombre devuelto no coincide")
    await assert_seller_data_gone(approved_id)

    status, list_payload = http_json(
        "GET",
        f"{BASE_URL}/api/admin/registrations?status=all",
        token=admin_token,
    )
    assert_ok(status == 200, f"Listar todas falló ({status}): {list_payload}")
    assert_ok(
        not any(item["id"] == approved_id for item in list_payload),
        "La tienda eliminada sigue apareciendo en el listado admin",
    )
    print("   OK aprobada eliminada con cascada")

    print("3. Rechazar solicitud y eliminarla…")
    rejected_id, _, _ = await register_test_store(suffix=f"rej-{unique_suffix()}")
    status, _ = http_json(
        "POST",
        f"{BASE_URL}/api/admin/registrations/{rejected_id}/reject",
        token=admin_token,
    )
    assert_ok(status == 200, "Rechazar solicitud de prueba falló")

    status, deleted = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{rejected_id}",
        token=admin_token,
    )
    assert_ok(status == 200, f"DELETE rechazada falló ({status}): {deleted}")
    await assert_seller_data_gone(rejected_id)
    print("   OK rechazada eliminada")

    print("4. Vencida y eliminarla…")
    expired_id, _, _ = await register_test_store(suffix=f"exp-{unique_suffix()}")
    await approve_registration(admin_token, expired_id)
    yesterday = to_utc_naive(utc_now()) - timedelta(days=1)
    await get_registrations_collection().update_one(
        {"_id": ObjectId(expired_id)},
        {"$set": {"status": "approved", "subscription_ends_at": yesterday}},
    )
    status, expired_list = http_json(
        "GET",
        f"{BASE_URL}/api/admin/registrations?status=expired",
        token=admin_token,
    )
    assert_ok(status == 200, f"List expired falló ({status}): {expired_list}")
    assert_ok(
        any(item["id"] == expired_id for item in expired_list),
        "La tienda de prueba no apareció como vencida",
    )

    status, deleted = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{expired_id}",
        token=admin_token,
    )
    assert_ok(status == 200, f"DELETE vencida falló ({status}): {deleted}")
    await assert_seller_data_gone(expired_id)
    print("   OK vencida eliminada")

    print("5. DELETE sin token admin debe fallar…")
    ghost_id = str(ObjectId())
    status, _ = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{ghost_id}",
    )
    assert_ok(status in (401, 403), f"DELETE sin auth debía fallar, respondió {status}")
    print(f"   OK sin auth -> {status}")

    print("6. DELETE de ID inexistente debe devolver 404…")
    missing_id = str(ObjectId())
    status, _ = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{missing_id}",
        token=admin_token,
    )
    assert_ok(status == 404, f"DELETE inexistente debía ser 404, fue {status}")
    print("   OK 404 en ID inexistente")


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
