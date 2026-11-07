"""El admin lista clientes y puede impedirles comprar sin cerrarles la cuenta."""

from __future__ import annotations

import unittest

from bson import ObjectId

from app.auth.utils import hash_password
from app.database import get_customers_collection, get_orders_collection
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import admin_auth_headers, api_client
from test_e2e.utils.database import mongo_configured, run_db

MARKER = "admin_customers_e2e_v1"
PASSWORD = "cliente123"


async def cleanup() -> None:
    await get_customers_collection().delete_many({MARKER: True})
    await get_orders_collection().delete_many({MARKER: True})


async def seed_customer() -> dict[str, str]:
    await cleanup()
    customer_id = ObjectId()
    now = to_utc_naive(utc_now())
    phone = f"{(int(str(customer_id), 16) % 90000000) + 10000000:08d}"
    await get_customers_collection().insert_one({
        "_id": customer_id,
        "full_name": "Cliente Admin E2E",
        "email": f"cliente-{customer_id}@admin-customers-e2e.test",
        "phone": phone,
        "identity_card": f"CI{str(customer_id)[-10:]}",
        "qvapay_username": "cliente-qva",
        "password_hash": hash_password(PASSWORD),
        "addresses": [],
        "favorite_product_ids": [],
        "favorites": [],
        "created_at": now,
        MARKER: True,
    })
    await get_orders_collection().insert_one({
        "buyer_id": str(customer_id),
        "status": "completed",
        "created_at": now,
        MARKER: True,
    })
    return {"customer_id": str(customer_id), "phone": phone}


def order_body() -> dict:
    return {
        "store_id": "507f1f77bcf86cd799439011",
        "items": [{
            "product_id": "producto-e2e",
            "name": "Arroz",
            "quantity": 1,
            "unit_price": 10,
            "currency": "CUP",
        }],
        "payment_method": "contact",
    }


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AdminCustomersE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.customer = run_db(seed_customer)

    @classmethod
    def tearDownClass(cls) -> None:
        run_db(cleanup)

    def test_revoked_customer_can_sign_in_but_cannot_order(self) -> None:
        headers = admin_auth_headers()
        with api_client() as client:
            listed = client.get("/api/admin/customers", headers=headers)
            self.assertEqual(listed.status_code, 200, listed.text)
            row = next(item for item in listed.json() if item["id"] == self.customer["customer_id"])
            self.assertEqual(row["full_name"], "Cliente Admin E2E")
            self.assertEqual(row["qvapay_username"], "cliente-qva")
            self.assertEqual(row["order_count"], 1)
            self.assertFalse(row["purchase_revoked"])

            revoked = client.patch(
                f"/api/admin/customers/{self.customer['customer_id']}/access",
                headers=headers,
                json={"purchase_revoked": True},
            )
            self.assertEqual(revoked.status_code, 200, revoked.text)
            self.assertTrue(revoked.json()["purchase_revoked"])
            self.assertEqual(revoked.json()["order_count"], 1)

            signed_in = client.post("/api/customers/login", json={
                "phone": self.customer["phone"],
                "password": PASSWORD,
            })
            self.assertEqual(signed_in.status_code, 200, signed_in.text)
            body = signed_in.json()
            self.assertTrue(body["access_token"])
            self.assertTrue(body["customer"]["purchase_revoked"])

            blocked = client.post(
                "/api/marketplace/orders",
                headers={"Authorization": f"Bearer {body['access_token']}"},
                json=order_body(),
            )
            self.assertEqual(blocked.status_code, 400, blocked.text)
            self.assertIn("revocado", blocked.json()["detail"])

            restored = client.patch(
                f"/api/admin/customers/{self.customer['customer_id']}/access",
                headers=headers,
                json={"purchase_revoked": False},
            )
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertFalse(restored.json()["purchase_revoked"])

            allowed_account = client.post("/api/marketplace/orders", headers={
                "Authorization": f"Bearer {body['access_token']}",
            }, json=order_body())
            self.assertEqual(allowed_account.status_code, 400, allowed_account.text)
            self.assertNotIn("revocado", allowed_account.json()["detail"])
