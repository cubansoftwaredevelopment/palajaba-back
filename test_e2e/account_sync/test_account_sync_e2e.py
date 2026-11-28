"""Sigue la sincronización por sección.

Cada cuenta manda solo fechas. El servidor responde true si el teléfono es
más reciente y false si es más antiguo. El guardado ocurre en una segunda
petición, y solo cuando la respuesta fue true.
"""

from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from datetime import timedelta

from bson import ObjectId
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.admin.routes import panel_router as admin_router
from app.admin.service import SETTINGS_ID
from app.auth.routes import auth_router
from app.auth.utils import (
    create_admin_token,
    create_customer_token,
    create_gestor_token,
    create_mensajero_token,
    create_seller_token,
)
from app.customer_accounts.routes import router as customer_router
from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_customers_collection,
    get_gestores_collection,
    get_mensajeros_collection,
    get_orders_collection,
    get_platform_settings_collection,
    get_registrations_collection,
)
from app.gestores.routes import router as gestor_router
from app.mensajeros.routes import panel_router as mensajero_router
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.database import mongo_configured, run_db

MARKER = "account_sync_e2e_v1"


# Borra solo los documentos de este test. El reloj del admin vive en ajustes globales.
async def cleanup() -> None:
    query = {MARKER: True}
    await get_customers_collection().delete_many(query)
    await get_registrations_collection().delete_many(query)
    await get_gestores_collection().delete_many(query)
    await get_mensajeros_collection().delete_many(query)
    await get_orders_collection().delete_many(query)
    await get_platform_settings_collection().update_one(
        {"_id": SETTINGS_ID},
        {"$unset": {"admin_section_clocks.sync-admin": ""}},
    )


def _iso(moment) -> str:
    return to_utc_naive(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


# App mínima: solo las rutas de sync, sin el arranque completo del servidor.
def _app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        await connect_to_mongo()
        yield
        await close_mongo_connection()

    app = FastAPI(lifespan=lifespan)
    app.include_router(customer_router)
    app.include_router(auth_router)
    app.include_router(gestor_router)
    app.include_router(mensajero_router)
    app.include_router(admin_router)
    return app


class AccountSyncE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        if not mongo_configured():
            self.skipTest("MongoDB no está configurado")
        run_db(cleanup)

    def tearDown(self) -> None:
        if mongo_configured():
            run_db(cleanup)

    def test_customer_section_dates_push_and_keep_orders(self) -> None:
        # 1. El servidor ya tiene direcciones y un pedido completado, ambos con fecha "ahora".
        async def seed():
            now = to_utc_naive(utc_now())
            customer_id = ObjectId()
            order_id = ObjectId()
            await get_customers_collection().insert_one({
                "_id": customer_id,
                "full_name": "Cliente Sync",
                "email": f"{customer_id}@sync.test",
                "phone": "55500001",
                "identity_card": f"CI{str(customer_id)[-8:]}",
                "password_hash": "x",
                "addresses": [{"id": "casa", "label": "Casa", "address": "Calle vieja 1"}],
                "favorite_product_ids": [],
                "favorites": [],
                "created_at": now,
                "section_updated_at": {"direcciones": now, "pedidos": now},
                MARKER: True,
            })
            await get_orders_collection().insert_one({
                "_id": order_id,
                "buyer_id": str(customer_id),
                "seller_id": str(ObjectId()),
                "status": "completed",
                "created_at": now,
                "updated_at": now,
                MARKER: True,
            })
            return str(customer_id), str(order_id), now

        customer_id, order_id, server_at = run_db(seed)
        headers = {"Authorization": f"Bearer {create_customer_token(customer_id=customer_id, full_name='Cliente Sync')}"}
        newer = _iso(server_at + timedelta(minutes=2))
        older = _iso(server_at - timedelta(minutes=2))

        with TestClient(_app()) as client:
            # 2. El teléfono dice que sus fechas son 2 minutos más nuevas. Esperamos true.
            compared = client.post(
                "/api/customers/me/sync",
                headers=headers,
                json={"direcciones": newer, "pedidos": newer},
            )
            self.assertEqual(compared.status_code, 200, compared.text)
            self.assertIs(compared.json()["direcciones"], True)
            self.assertIs(compared.json()["pedidos"], True)

            # 3. Como direcciones dio true, el teléfono envía la lista nueva y el servidor la guarda.
            saved = client.put(
                "/api/customers/me/sync/direcciones",
                headers=headers,
                json={"updated_at": newer, "data": [{"id": "trabajo", "label": "Trabajo", "address": "Calle nueva 8"}]},
            )
            self.assertEqual(saved.status_code, 200, saved.text)

            # 4. Pedidos también dio true, pero el cuerpo de un pedido no cambia el estado del servidor.
            kept = client.put(
                "/api/customers/me/sync/pedidos",
                headers=headers,
                json={"updated_at": newer, "data": [{"id": order_id, "status": "cancelled"}]},
            )
            self.assertEqual(kept.status_code, 200, kept.text)

            # 5. Una fecha 2 minutos más vieja responde false y el guardado se rechaza.
            stale = client.post("/api/customers/me/sync", headers=headers, json={"direcciones": older})
            self.assertEqual(stale.status_code, 200, stale.text)
            self.assertIs(stale.json()["direcciones"], False)
            rejected = client.put(
                "/api/customers/me/sync/direcciones",
                headers=headers,
                json={"updated_at": older, "data": [{"id": "otra", "label": "Otra", "address": "No debe guardarse"}]},
            )
            self.assertEqual(rejected.status_code, 409, rejected.text)

        # 6. En la base quedó la dirección nueva y el pedido sigue completado.
        async def read():
            customer = await get_customers_collection().find_one({"_id": ObjectId(customer_id)})
            order = await get_orders_collection().find_one({"_id": ObjectId(order_id)})
            return customer, order

        customer, order = run_db(read)
        self.assertEqual(customer["addresses"][0]["label"], "Trabajo")
        self.assertEqual(order["status"], "completed")

    def test_other_roles_follow_the_same_date_rule(self) -> None:
        # 1. Tienda, gestor y mensajero empiezan con su fecha de sección en "ahora".
        async def seed():
            now = to_utc_naive(utc_now())
            seller_id = ObjectId()
            gestor_id = ObjectId()
            mensajero_id = ObjectId()
            await get_registrations_collection().insert_one({
                "_id": seller_id,
                "store_name": f"Sync {seller_id}",
                "phone": "55500002",
                "biography": "Antes",
                "created_at": now,
                "section_updated_at": {"perfil": now},
                MARKER: True,
            })
            await get_gestores_collection().insert_one({
                "_id": gestor_id,
                "seller_id": seller_id,
                "username": "syncgestor",
                "is_active": True,
                "selected_products": [],
                "created_at": now,
                "updated_at": now,
                MARKER: True,
            })
            await get_mensajeros_collection().insert_one({
                "_id": mensajero_id,
                "seller_id": seller_id,
                "first_name": "Ana",
                "last_name": "Ruiz",
                "phone": "55500003",
                "username": "syncmensajero",
                "is_active": True,
                "vehicles": [],
                "created_at": now,
                "updated_at": now,
                MARKER: True,
            })
            return str(seller_id), str(gestor_id), str(mensajero_id), now

        seller_id, gestor_id, mensajero_id, server_at = run_db(seed)
        newer = _iso(server_at + timedelta(minutes=3))
        older = _iso(server_at - timedelta(minutes=3))
        seller_headers = {"Authorization": f"Bearer {create_seller_token(seller_id=seller_id, store_name='Sync')}"}
        gestor_headers = {"Authorization": f"Bearer {create_gestor_token(gestor_id=gestor_id, seller_id=seller_id, username='syncgestor')}"}
        mensajero_headers = {"Authorization": f"Bearer {create_mensajero_token(mensajero_id=mensajero_id, seller_id=seller_id, username='syncmensajero')}"}
        admin_headers = {"Authorization": f"Bearer {create_admin_token(username='sync-admin', admin_id='sync-admin')}"}

        with TestClient(_app()) as client:
            # 2. Tienda: fecha mayor -> true, se guarda la biografía, fecha menor -> false.
            seller = client.post("/api/auth/me/sync", headers=seller_headers, json={"perfil": newer})
            self.assertEqual(seller.status_code, 200, seller.text)
            self.assertIs(seller.json()["perfil"], True)
            pushed = client.put(
                "/api/auth/me/sync/perfil",
                headers=seller_headers,
                json={"updated_at": newer, "data": {"biography": "Despues"}},
            )
            self.assertEqual(pushed.status_code, 200, pushed.text)
            stale = client.post("/api/auth/me/sync", headers=seller_headers, json={"perfil": older})
            self.assertIs(stale.json()["perfil"], False)

            # 3. Gestor: fecha mayor -> true y se guardan los productos elegidos.
            gestor = client.post("/api/gestores/me/sync", headers=gestor_headers, json={"productos": newer})
            self.assertEqual(gestor.status_code, 200, gestor.text)
            self.assertIs(gestor.json()["productos"], True)
            gestor_push = client.put(
                "/api/gestores/me/sync/productos",
                headers=gestor_headers,
                json={"updated_at": newer, "data": [{"product_id": "prod-1", "margin_amount": 5}]},
            )
            self.assertEqual(gestor_push.status_code, 200, gestor_push.text)

            # 4. Mensajero: fecha mayor guarda el vehículo; una fecha menor responde false.
            mensajero = client.post("/api/mensajeros/me/sync", headers=mensajero_headers, json={"vehiculos": newer})
            self.assertEqual(mensajero.status_code, 200, mensajero.text)
            self.assertIs(mensajero.json()["vehiculos"], True)
            mensajero_push = client.put(
                "/api/mensajeros/me/sync/vehiculos",
                headers=mensajero_headers,
                json={"updated_at": newer, "data": [{"id": "bici-1", "vehicle_type": "bicicleta", "plate": "B1"}]},
            )
            self.assertEqual(mensajero_push.status_code, 200, mensajero_push.text)
            mensajero_stale = client.post("/api/mensajeros/me/sync", headers=mensajero_headers, json={"vehiculos": older})
            self.assertIs(mensajero_stale.json()["vehiculos"], False)

            # 5. Admin: la misma regla sobre estadísticas, sin pisar otros datos.
            admin = client.post("/api/admin/me/sync", headers=admin_headers, json={"estadisticas": newer})
            self.assertEqual(admin.status_code, 200, admin.text)
            self.assertIs(admin.json()["estadisticas"], True)
            admin_push = client.put(
                "/api/admin/me/sync/estadisticas",
                headers=admin_headers,
                json={"updated_at": newer, "data": {}},
            )
            self.assertEqual(admin_push.status_code, 200, admin_push.text)
            admin_stale = client.post("/api/admin/me/sync", headers=admin_headers, json={"estadisticas": older})
            self.assertIs(admin_stale.json()["estadisticas"], False)

        # 6. Lo que sí debía cambiar quedó guardado: biografía, producto y vehículo.
        async def read():
            seller_doc = await get_registrations_collection().find_one({"_id": ObjectId(seller_id)})
            gestor_doc = await get_gestores_collection().find_one({"_id": ObjectId(gestor_id)})
            mensajero_doc = await get_mensajeros_collection().find_one({"_id": ObjectId(mensajero_id)})
            return seller_doc, gestor_doc, mensajero_doc

        seller_doc, gestor_doc, mensajero_doc = run_db(read)
        self.assertEqual(seller_doc["biography"], "Despues")
        self.assertEqual(gestor_doc["selected_products"][0]["product_id"], "prod-1")
        self.assertEqual(mensajero_doc["vehicles"][0]["vehicle_type"], "bicicleta")
