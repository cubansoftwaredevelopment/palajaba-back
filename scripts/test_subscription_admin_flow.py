"""Prueba integración: sync expired, renovar y editar suscripción desde admin."""

from __future__ import annotations

import asyncio
import json
import os
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
    get_registrations_collection,
)
from app.security import create_admin_token
from app.utils.datetime import to_utc_naive, utc_now

BASE_URL = "http://127.0.0.1:8081"
HEALTH_URL = f"{BASE_URL}/api/health"


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


def wait_for_backend(max_seconds: int = 45) -> None:
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("El backend no respondió a tiempo en /api/health")


async def backdate_to_expired(registration_id: str) -> None:
    collection = get_registrations_collection()
    yesterday = to_utc_naive(utc_now()) - timedelta(days=1)
    result = await collection.update_one(
        {"_id": ObjectId(registration_id)},
        {
            "$set": {
                "status": "approved",
                "subscription_ends_at": yesterday,
            }
        },
    )
    assert_ok(result.modified_count == 1, "No se pudo backdatear la suscripción de prueba")


async def cleanup_registration(registration_id: str) -> None:
    collection = get_registrations_collection()
    await collection.delete_one({"_id": ObjectId(registration_id)})


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


async def run_tests() -> None:
    suffix = uuid.uuid4().hex[:8]
    transfer_id = f"TEST-SUB-{suffix}"
    store_name = f"Tienda Test Sub {suffix}"
    phone = f"{int(suffix, 16) % 100000000:08d}"

    print("Esperando backend...")
    wait_for_backend()

    print("1. Registrar tienda de prueba…")
    status, payload = http_json(
        "POST",
        f"{BASE_URL}/api/register",
        body={
            "transfer_id": transfer_id,
            "store_name": store_name,
            "phone": phone,
            "password": "TestSub2026!",
            "billing_period": "monthly",
            "plan_tier": "standard",
        },
    )
    assert_ok(status == 201, f"Registro falló ({status}): {payload}")
    registration_id = payload["id"]
    print(f"   OK id={registration_id}")

    print("2. Token admin…")
    admin_token = await get_admin_token()
    print("   OK admin token")

    print("3. Aprobar solicitud…")
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
    print("   OK approved")

    await connect_to_mongo()
    try:
        print("4. Simular vencimiento (fecha pasada)…")
        await backdate_to_expired(registration_id)

        print("5. Listar vencidas - debe aparecer y sincronizar a expired...")
        status, expired_list = http_json(
            "GET",
            f"{BASE_URL}/api/admin/registrations?status=expired",
            token=admin_token,
        )
        assert_ok(status == 200, f"List expired falló ({status}): {expired_list}")
        match = next((item for item in expired_list if item["id"] == registration_id), None)
        assert_ok(match is not None, "La tienda de prueba no aparece en Vencidas")
        assert_ok(match["status"] == "expired", "El estado debe ser expired tras sync")
        print(f"   OK expired, vencio {match.get('subscription_ends_at')}")

        print("6. Renovar plan - vuelve a approved...")
        renew_params = urllib.parse.urlencode(
            {
                "payment_amount_cup": "4",
                "subscription_ends_at": (to_utc_naive(utc_now()) + timedelta(days=365)).strftime("%Y-%m-%d"),
                "plan_tier": "premium",
                "billing_period": "yearly",
            }
        )
        status, renewed = http_json(
            "POST",
            f"{BASE_URL}/api/admin/registrations/{registration_id}/renew?{renew_params}",
            token=admin_token,
        )
        assert_ok(status == 200, f"Renovar falló ({status}): {renewed}")
        assert_ok(renewed["status"] == "approved", "Tras renovar debe volver a approved")
        assert_ok(renewed["plan_tier"] == "premium", "Plan debe ser premium tras renovar")
        assert_ok(renewed["billing_period"] == "yearly", "Facturación debe ser yearly tras renovar")
        print("   OK renewed -> approved, premium, yearly")

        print("7. Editar suscripción en tienda aprobada…")
        edit_params = urllib.parse.urlencode(
            {
                "subscription_ends_at": (to_utc_naive(utc_now()) + timedelta(days=60)).strftime("%Y-%m-%d"),
                "plan_tier": "standard",
                "billing_period": "monthly",
            }
        )
        status, edited = http_json(
            "PATCH",
            f"{BASE_URL}/api/admin/registrations/{registration_id}/subscription?{edit_params}",
            token=admin_token,
        )
        assert_ok(status == 200, f"Editar suscripción falló ({status}): {edited}")
        assert_ok(edited["plan_tier"] == "standard", "Plan editado debe ser standard")
        assert_ok(edited["billing_period"] == "monthly", "Facturación editada debe ser monthly")
        print("   OK subscription edited")

        print("8. Login vendedor tras renovar…")
        status, login_payload = http_json(
            "POST",
            f"{BASE_URL}/api/auth/login",
            body={
                "method": "phone",
                "phone": phone,
                "password": "TestSub2026!",
            },
        )
        assert_ok(status == 200, f"Login vendedor falló ({status}): {login_payload}")
        assert_ok("access_token" in login_payload, "Login debe devolver access_token")
        print("   OK seller login")

    finally:
        print("9. Limpiar datos de prueba…")
        await cleanup_registration(registration_id)
        await close_mongo_connection()
        print("   OK cleanup")

    print("\n[OK] Todas las pruebas pasaron.")


if __name__ == "__main__":
    asyncio.run(run_tests())
