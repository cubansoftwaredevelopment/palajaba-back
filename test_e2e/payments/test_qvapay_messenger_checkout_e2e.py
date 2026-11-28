"""E2E: el cliente compra con QvaPay y la tienda le paga al mensajero verificado."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.auth.utils import create_customer_token
from app.config import settings
from app.database import (
    get_customers_collection,
    get_mensajeria_asignaciones_collection,
    get_mensajeria_batches_collection,
    get_mensajeros_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.payments.qvapay import QvaPayInvoice
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.payments.utils.fixtures import SECRET, sign_webhook
from test_e2e.products.utils.fixtures import seed_seller
from test_e2e.utils.api import api_client, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db

MARKER = "qvapay_messenger_e2e"
STORE_USER = "tiendae2e"
COURIER_USER = "mensajeroe2e"


# Borra el cliente, el pedido, el mensajero y la tienda que sembró este caso.
async def cleanup_case(seller_id: str | None) -> None:
    customers = get_customers_collection()
    buyer_ids = [str(doc["_id"]) async for doc in customers.find({MARKER: True}, {"_id": 1})]
    if buyer_ids:
        await get_orders_collection().delete_many({"buyer_id": {"$in": buyer_ids}})
    await customers.delete_many({MARKER: True})
    if not seller_id:
        return
    seller_oid = ObjectId(seller_id)
    await get_orders_collection().delete_many({"seller_id": seller_id})
    await get_mensajeria_asignaciones_collection().delete_many({"seller_id": seller_oid})
    await get_mensajeria_batches_collection().delete_many({"seller_id": seller_oid})
    await get_mensajeros_collection().delete_many({"seller_id": seller_oid})
    await get_registrations_collection().delete_many({"_id": seller_oid})


async def seed_customer() -> str:
    customer_id = ObjectId()
    now = to_utc_naive(utc_now())
    await get_customers_collection().insert_one({
        "_id": customer_id,
        "full_name": "José QvaPay",
        "email": f"jose-{customer_id}@qvapay-e2e.test",
        "phone": f"{(int(str(customer_id), 16) % 90000000) + 10000000:08d}",
        "created_at": now,
        "updated_at": now,
        MARKER: True,
    })
    return str(customer_id)


# QvaPay no se consulta: verificar un usuario solo normaliza el alias que envió la API.
def _echo_username():
    async def echo(username: str) -> str:
        return username.strip().lstrip("@").lower()

    return echo


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class QvaPayMessengerCheckoutE2ETests(unittest.TestCase):
    def test_qvapay_purchase_pays_verified_messenger(self) -> None:
        # Premium incluye mensajeros. Un plan básico no puede crearlos ni asignarlos.
        seller = seed_seller(plan_tier="premium")
        seller_id = seller["seller_id"]
        customer_id = run_db(seed_customer)
        try:
            self._run(seller, customer_id)
        finally:
            run_db(lambda: cleanup_case(seller_id))

    def _run(self, seller: dict[str, str], customer_id: str) -> None:
        seller_headers = seller_auth_headers(seller_id=seller["seller_id"], store_name=seller["store_name"])
        customer_headers = {
            "Authorization": f"Bearer {create_customer_token(customer_id=customer_id, full_name='José QvaPay')}",
        }
        transfers: list[dict] = []

        # Cada liberación queda anotada. La primera es la tienda; la segunda, el mensajero.
        async def transfer_to_user(**kwargs):
            transfers.append(kwargs)
            return f"tx-{len(transfers)}"

        async def create_invoice(**kwargs):
            return QvaPayInvoice(
                "https://qvapay.com/pay/mensajero-e2e",
                f"tx-mensajero-{seller['seller_id'][-8:]}",
                float(kwargs["amount"]),
                kwargs["remote_id"],
                {},
            )

        # 400 CUP = 1 USD. La comisión de la plataforma es el 10 % de producto + domicilio.
        # Con malanga a 400 CUP y domicilio a 400 CUP la factura es 1 + 1 + 0.2 = 2.2 USD.
        settings_patch = patch.multiple(settings, qvapay_app_secret=SECRET, qvapay_app_id="app-e2e")
        with settings_patch, api_client() as client, \
             patch("app.payments.service.get_cup_per_unit", return_value={"CUP": 1, "USD": 400}), \
             patch("app.admin.service.get_platform_settings", new_callable=AsyncMock, return_value=SimpleNamespace(transaction_fee_percent=10)), \
             patch("app.payments.service.create_invoice", new_callable=AsyncMock, side_effect=create_invoice), \
             patch("app.payments.service.verify_qvapay_username", new_callable=AsyncMock, side_effect=_echo_username()), \
             patch("app.mensajeros.service.verify_qvapay_username", new_callable=AsyncMock, side_effect=_echo_username()), \
             patch("app.payments.service.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.qvapay.qvapay_escrow_configured", return_value=True), \
             patch("app.payments.service.transfer_to_user", new_callable=AsyncMock, side_effect=transfer_to_user), \
             patch("app.mensajeros.payout.transfer_to_user", new_callable=AsyncMock, side_effect=transfer_to_user), \
             patch("app.payments.service.send_custom_sms", new_callable=AsyncMock), \
             patch("app.payments.service.publish_seller_notification", new_callable=AsyncMock), \
             patch("app.orders.service.notification_service.notify_seller_new_order", new_callable=AsyncMock):
            # Tienda y cliente dejan un usuario QvaPay verificado. Sin eso no se puede cobrar.
            store_account = client.put(
                "/api/auth/me/payment-methods/qvapay",
                headers=seller_headers,
                json={"username": STORE_USER},
            )
            self.assertEqual(store_account.status_code, 200, store_account.text)
            self.assertEqual(store_account.json()["verified"], True)

            buyer_account = client.put(
                "/api/customers/me/payment-methods/qvapay",
                headers=customer_headers,
                json={"username": "joseqva"},
            )
            self.assertEqual(buyer_account.status_code, 200, buyer_account.text)
            self.assertEqual(buyer_account.json()["verified"], True)

            # El cliente compra con domicilio. El pedido queda retenido hasta que la tienda acepte.
            created = client.post(
                "/api/marketplace/orders",
                headers=customer_headers,
                json={
                    "store_id": seller["seller_id"],
                    "items": [{
                        "product_id": str(ObjectId()),
                        "name": "Malanga",
                        "quantity": 1,
                        "unit_price": 400,
                        "currency": "CUP",
                    }],
                    "payment_currency": "CUP",
                    "payment_method": "qvapay",
                    "delivery": {
                        "recipient_name": "José QvaPay",
                        "address": "Calle E2E 12",
                        "phone_primary": "51234567",
                    },
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            order_id = created.json()["id"]
            self.assertEqual(created.json()["payment_method"], "qvapay")

            # La tienda fija el domicilio en 400 CUP y QvaPay emite la factura de 2.2 USD.
            accepted = client.post(
                f"/api/auth/me/orders/{order_id}/qvapay/accept",
                headers=seller_headers,
                json={"delivery_price": 400, "delivery_currency": "CUP"},
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(accepted.json()["invoice_amount_usd"], 2.2)

            # El webhook de QvaPay marca el pedido como pagado. El dinero sigue retenido.
            webhook = json.dumps({
                "remote_id": f"store-order-{order_id}",
                "transaction_uuid": f"tx-mensajero-{seller['seller_id'][-8:]}",
                "status": "paid",
            }).encode()
            hooked = client.post(
                "/api/payments/qvapay/webhook",
                content=webhook,
                headers={"x-qvapay-signature": sign_webhook(webhook), "content-type": "application/json"},
            )
            self.assertEqual(hooked.status_code, 200, hooked.text)

            # Rocío existe, pero todavía no verificó QvaPay.
            alias = f"rocio{seller['seller_id'][-6:]}"
            messenger_phone = f"{(int(seller['seller_id'], 16) % 80000000) + 20000000:08d}"
            messenger = client.post(
                "/api/auth/me/mensajeros",
                headers=seller_headers,
                json={
                    "first_name": "Rocío",
                    "last_name": "Mensajera",
                    "phone": messenger_phone,
                    "username": alias,
                },
            )
            self.assertEqual(messenger.status_code, 200, messenger.text)
            messenger_id = messenger.json()["id"]
            self.assertEqual(messenger.json()["qvapay_verified"], False)

            # Pagarle por QvaPay a un mensajero sin usuario verificado tiene que fallar.
            blocked = client.post(
                "/api/auth/me/mensajeros/batches",
                headers=seller_headers,
                json={
                    "mensajero_id": messenger_id,
                    "orders": [{
                        "order_id": order_id,
                        "pay_via": "qvapay",
                        "fee_amount": 200,
                        "fee_currency": "CUP",
                    }],
                },
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertIn("no tiene QvaPay verificado", blocked.json()["detail"])

            # El mensajero crea su clave y verifica el usuario mensajeroe2e en QvaPay.
            login = client.post("/api/mensajeros/login", json={"username": alias})
            self.assertEqual(login.status_code, 200, login.text)
            setup = client.post("/api/mensajeros/setup", json={
                "setup_token": login.json()["requires_setup"]["setup_token"],
                "password": "clave-e2e",
            })
            self.assertEqual(setup.status_code, 200, setup.text)
            courier_headers = {"Authorization": f"Bearer {setup.json()['access_token']}"}
            verified = client.put(
                "/api/mensajeros/me/qvapay",
                headers=courier_headers,
                json={"username": COURIER_USER},
            )
            self.assertEqual(verified.status_code, 200, verified.text)
            self.assertEqual(verified.json()["qvapay_username"], COURIER_USER)
            self.assertEqual(verified.json()["qvapay_verified"], True)

            # 200 CUP de los 400 del domicilio: la mitad, 0.50 USD, queda para el mensajero.
            assigned = client.post(
                "/api/auth/me/mensajeros/batches",
                headers=seller_headers,
                json={
                    "mensajero_id": messenger_id,
                    "orders": [{
                        "order_id": order_id,
                        "pay_via": "qvapay",
                        "fee_amount": 200,
                        "fee_currency": "CUP",
                    }],
                },
            )
            self.assertEqual(assigned.status_code, 200, assigned.text)

            # Al aceptar la evidencia se libera el pago: 1.50 USD a la tienda y 0.50 USD al mensajero.
            content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Entregado"}]}]}
            evidence = client.post(
                f"/api/auth/me/orders/{order_id}/evidence",
                headers=seller_headers,
                json={"content": content},
            )
            self.assertEqual(evidence.status_code, 200, evidence.text)
            decision = client.post(
                f"/api/customers/me/orders/{order_id}/qvapay/evidence/accept",
                headers=customer_headers,
            )
            self.assertEqual(decision.status_code, 200, decision.text)
            self.assertEqual(decision.json()["accepted"], True)

        # La tienda cobra producto + domicilio menos la parte del mensajero (2.00 - 0.50).
        code = order_id[-6:].upper()
        self.assertEqual(
            [(item["username"], item["amount"], item["idempotency_key"], item["description"]) for item in transfers],
            [
                (STORE_USER, 1.5, f"store-order-{order_id}-release", f"Liquidación pedido {code}"),
                (COURIER_USER, 0.5, f"courier-order-{order_id}-release", f"Mensajería pedido {code}"),
            ],
        )
        # tx-2 es la transferencia al mensajero. La asignación queda pagada por QvaPay.
        stored = run_db(lambda: get_orders_collection().find_one({"_id": ObjectId(order_id)}))
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["qvapay"]["release_status"], "released")
        self.assertEqual(stored["collected_total"], 1.5)
        assignment = run_db(lambda: get_mensajeria_asignaciones_collection().find_one({"order_id": ObjectId(order_id)}))
        self.assertEqual(assignment["pay_via"], "qvapay")
        self.assertEqual(assignment["fee_amount_usd"], 0.5)
        self.assertEqual(assignment["qvapay_transfer_id"], "tx-2")
