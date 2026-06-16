"""
Prueba de integración: estadísticas de negocios por provincia (admin).

Levanta el backend si no está en marcha, siembra tiendas de prueba en Mongo,
consulta GET /api/admin/stats/businesses-by-province y verifica conteos y auth.

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_admin_businesses_by_province.py
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
from app.database import close_mongo_connection, connect_to_mongo, get_registrations_collection
from app.security import create_admin_token
from app.utils.datetime import to_utc_naive, utc_now

BASE_URL = "http://127.0.0.1:8081"
HEALTH_URL = f"{BASE_URL}/api/health"
STATS_URL = f"{BASE_URL}/api/admin/stats/businesses-by-province"
BACKEND_PROC: subprocess.Popen | None = None
TEST_PORT = 8081


def set_base_url(port: int) -> None:
    global BASE_URL, HEALTH_URL, STATS_URL, TEST_PORT
    TEST_PORT = port
    BASE_URL = f"http://127.0.0.1:{port}"
    HEALTH_URL = f"{BASE_URL}/api/health"
    STATS_URL = f"{BASE_URL}/api/admin/stats/businesses-by-province"


def stats_route_exists() -> bool:
    status, _ = http_json("GET", STATS_URL)
    return status != 404

LA_HABANA_AREA = {
    "province_id": "la-habana",
    "province_name": "La Habana",
    "municipality_id": "playa",
    "municipality_name": "Playa",
}
MATANZAS_AREA = {
    "province_id": "matanzas",
    "province_name": "Matanzas",
    "municipality_id": "matanzas",
    "municipality_name": "Matanzas",
}


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

    for port in (8081, 8082):
        set_base_url(port)
        try:
            wait_for_backend(max_seconds=3)
        except RuntimeError:
            continue
        if stats_route_exists():
            print(f"Backend con ruta de stats en :{port}")
            return None

    set_base_url(8082)
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
    assert_ok(stats_route_exists(), "El backend levantado no expone /api/admin/stats/businesses-by-province")
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


def province_count(payload: dict, province_id: str) -> int:
    for item in payload.get("provinces", []):
        if item.get("province_id") == province_id:
            return int(item["count"])
    return 0


async def get_admin_token() -> str:
    await connect_to_mongo()
    from app.database import get_admins_collection

    admin = await get_admins_collection().find_one(
        {"username": settings.admin_username, "is_active": True}
    )
    assert_ok(admin is not None, f"Admin «{settings.admin_username}» no existe en la base de datos")
    return create_admin_token(
        username=admin["username"],
        admin_id=str(admin["_id"]),
    )


async def register_test_store(*, suffix: str) -> str:
    transfer_id = f"TEST-PROV-{suffix}"
    store_name = f"Tienda Provincia Test {suffix}"
    phone = unique_phone()
    password = "TestProvince2026!"

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
    return payload["id"]


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


async def set_business_area(registration_id: str, area: dict) -> None:
    await get_registrations_collection().update_one(
        {"_id": ObjectId(registration_id)},
        {"$set": {"business_area": area}},
    )


async def delete_registration(admin_token: str, registration_id: str) -> None:
    status, payload = http_json(
        "DELETE",
        f"{BASE_URL}/api/admin/registrations/{registration_id}",
        token=admin_token,
    )
    assert_ok(status == 200, f"DELETE cleanup falló ({status}): {payload}")


def assert_stats_shape(payload: dict) -> None:
    assert_ok(isinstance(payload, dict), "La respuesta debe ser un objeto JSON")
    for key in ("total_with_location", "without_location", "provinces"):
        assert_ok(key in payload, f"Falta el campo «{key}» en la respuesta")
    assert_ok(isinstance(payload["provinces"], list), "«provinces» debe ser una lista")
    for item in payload["provinces"]:
        assert_ok(
            {"province_id", "province_name", "count"} <= set(item.keys()),
            f"Provincia incompleta: {item}",
        )
        assert_ok(item["count"] > 0, "Solo deben listarse provincias con count > 0")


def assert_sorted_descending(payload: dict) -> None:
    counts = [int(item["count"]) for item in payload["provinces"]]
    assert_ok(counts == sorted(counts, reverse=True), "Las provincias deben ordenarse por count descendente")


async def run_tests() -> None:
    admin_token = await get_admin_token()
    seeded_ids: list[str] = []

    try:
        print("1. GET sin token admin debe fallar…")
        status, _ = http_json("GET", STATS_URL)
        assert_ok(status in (401, 403), f"GET sin auth debía fallar, respondió {status}")
        print(f"   OK sin auth -> {status}")

        print("2. Baseline de estadísticas por provincia…")
        status, baseline = http_json("GET", STATS_URL, token=admin_token)
        assert_ok(status == 200, f"GET stats falló ({status}): {baseline}")
        assert_stats_shape(baseline)
        assert_sorted_descending(baseline)
        print("   OK baseline válido")

        print("3. Sembrar tiendas de prueba (2 La Habana, 1 Matanzas, 1 sin ubicación, 1 pendiente)…")
        habana_a = await register_test_store(suffix=f"hab-a-{unique_suffix()}")
        habana_b = await register_test_store(suffix=f"hab-b-{unique_suffix()}")
        matanzas = await register_test_store(suffix=f"mat-{unique_suffix()}")
        no_location = await register_test_store(suffix=f"noloc-{unique_suffix()}")
        pending = await register_test_store(suffix=f"pend-{unique_suffix()}")
        seeded_ids.extend([habana_a, habana_b, matanzas, no_location, pending])

        for registration_id in (habana_a, habana_b, matanzas, no_location):
            await approve_registration(admin_token, registration_id)

        await set_business_area(habana_a, LA_HABANA_AREA)
        await set_business_area(habana_b, LA_HABANA_AREA)
        await set_business_area(matanzas, MATANZAS_AREA)
        await set_business_area(pending, LA_HABANA_AREA)
        print("   OK datos sembrados")

        print("4. Verificar conteos vía API…")
        status, after = http_json("GET", STATS_URL, token=admin_token)
        assert_ok(status == 200, f"GET stats tras seed falló ({status}): {after}")
        assert_stats_shape(after)
        assert_sorted_descending(after)

        delta_total = int(after["total_with_location"]) - int(baseline["total_with_location"])
        delta_without = int(after["without_location"]) - int(baseline["without_location"])
        delta_habana = province_count(after, "la-habana") - province_count(baseline, "la-habana")
        delta_matanzas = province_count(after, "matanzas") - province_count(baseline, "matanzas")

        assert_ok(delta_total == 3, f"total_with_location debía subir 3, subió {delta_total}")
        assert_ok(delta_without == 1, f"without_location debía subir 1, subió {delta_without}")
        assert_ok(delta_habana == 2, f"La Habana debía subir 2, subió {delta_habana}")
        assert_ok(delta_matanzas == 1, f"Matanzas debía subir 1, subió {delta_matanzas}")

        recomputed_total = sum(int(item["count"]) for item in after["provinces"])
        assert_ok(
            recomputed_total == int(after["total_with_location"]),
            "total_with_location debe coincidir con la suma de provinces",
        )
        print("   OK conteos correctos")

        print("5. Verificar servicio directo contra Mongo…")
        from app.services.admin_stats import get_businesses_by_province

        service_result = await get_businesses_by_province()
        assert_ok(
            service_result.total_with_location == int(after["total_with_location"]),
            "El servicio y la API deben devolver el mismo total_with_location",
        )
        assert_ok(
            service_result.without_location == int(after["without_location"]),
            "El servicio y la API deben devolver el mismo without_location",
        )
        service_habana = next(
            (item.count for item in service_result.provinces if item.province_id == "la-habana"),
            0,
        )
        assert_ok(
            service_habana == province_count(after, "la-habana"),
            "El servicio y la API deben coincidir en La Habana",
        )
        print("   OK servicio alineado con API")

    finally:
        print("6. Limpiar tiendas de prueba…")
        for registration_id in reversed(seeded_ids):
            try:
                await delete_registration(admin_token, registration_id)
            except AssertionError as exc:
                print(f"   AVISO: no se pudo borrar {registration_id}: {exc}")
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
