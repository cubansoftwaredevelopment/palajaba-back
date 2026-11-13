"""Eliminación física de cuentas de cliente y tienda conservando pedidos."""

from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.auth.utils import hash_password
from app.database import (
    get_catalog_products_collection,
    get_customer_devices_collection,
    get_customer_notifications_collection,
    get_customers_collection,
    get_gestores_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.utils.datetime import to_utc_naive, utc_now
from test_e2e.utils.api import api_client, customer_auth_headers, seller_auth_headers
from test_e2e.utils.database import mongo_configured, run_db
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID

MARKER = "account_deletion_e2e_v1"
PASSWORD = "clave123"


async def cleanup() -> None:
    await get_customers_collection().delete_many({MARKER: True})
    await get_registrations_collection().delete_many({MARKER: True})
    await get_catalog_products_collection().delete_many({MARKER: True})
    await get_orders_collection().delete_many({MARKER: True})
    await get_gestores_collection().delete_many({MARKER: True})
    await get_customer_notifications_collection().delete_many({MARKER: True})
    await get_customer_devices_collection().delete_many({MARKER: True})


def _phone_from_oid(oid: ObjectId) -> str:
    return f"{(int(str(oid), 16) % 90000000) + 10000000:08d}"


async def seed_order_pair(*, status: str = "completed") -> dict[str, str]:
    """Cliente + tienda + pedido compartido con snapshots denormalizados."""
    customer_id = ObjectId()
    seller_id = ObjectId()
    product_id = ObjectId()
    order_id = ObjectId()
    gestor_id = ObjectId()
    now = to_utc_naive(utc_now())
    customer_phone = _phone_from_oid(customer_id)
    seller_phone = _phone_from_oid(seller_id)
    store_name = f"TEST Delete {seller_id}"
    buyer_name = "Cliente Delete E2E"
    buyer_email = f"cliente-{customer_id}@account-deletion-e2e.test"
    product_name = "Producto Delete"
    line_total = 25.0

    await get_customers_collection().insert_one({
        "_id": customer_id,
        "full_name": buyer_name,
        "email": buyer_email,
        "phone": customer_phone,
        "identity_card": f"CI{str(customer_id)[-10:]}",
        "password_hash": hash_password(PASSWORD),
        "profile_photo_url": "https://example.com/customer.jpg",
        "addresses": [{"id": "addr-1", "label": "Casa", "address": "Calle 1"}],
        "favorite_product_ids": [str(product_id)],
        "favorites": [{"id": str(product_id), "name": product_name}],
        "created_at": now,
        MARKER: True,
    })
    await get_customer_notifications_collection().insert_one({
        "_id": ObjectId(),
        "customer_id": customer_id,
        "title": "Aviso",
        "content": "Test",
        "kind": "order_updated",
        "created_at": now,
        MARKER: True,
    })
    await get_customer_devices_collection().insert_one({
        "_id": ObjectId(),
        "customer_id": customer_id,
        "token": f"device-{customer_id}",
        "platform": "android",
        "updated_at": now,
        MARKER: True,
    })
    await get_registrations_collection().insert_one({
        "_id": seller_id,
        "status": "approved",
        "store_name": store_name,
        "store_slug": f"test-delete-{seller_id}",
        "phone": seller_phone,
        "email": f"tienda.{seller_id}@account-deletion-e2e.test",
        "password_hash": hash_password(PASSWORD),
        "billing_period": "monthly",
        "plan_tier": "standard",
        "is_trial": False,
        "profile_photo_url": "https://example.com/store.jpg",
        "store_banners": [{"id": "b1", "image_url": "https://example.com/banner.jpg"}],
        "category_ids": ["otros"],
        "offers_delivery": False,
        "business_area": {
            "province_id": PROVINCE_ID,
            "province_name": "La Habana",
            "municipality_id": SELLER_MUNICIPALITY_ID,
            "municipality_name": "Playa",
        },
        "subscription_starts_at": now - timedelta(days=3),
        "subscription_ends_at": now + timedelta(days=20),
        "created_at": now,
        "updated_at": now,
        MARKER: True,
    })
    await get_catalog_products_collection().insert_one({
        "_id": product_id,
        "seller_id": str(seller_id),
        "name": product_name,
        "base_price": line_total,
        "base_currency": "CUP",
        "image_url": "https://example.com/product.jpg",
        "images": [{"image_url": "https://example.com/product-2.jpg", "is_frontal": True}],
        "created_at": now,
        MARKER: True,
    })
    await get_gestores_collection().insert_one({
        "_id": gestor_id,
        "seller_id": seller_id,
        "username": f"gestor{str(seller_id)[-6:]}",
        "created_at": now,
        MARKER: True,
    })
    await get_orders_collection().insert_one({
        "_id": order_id,
        "seller_id": str(seller_id),
        "store_name": store_name,
        "buyer_id": str(customer_id),
        "buyer_name": buyer_name,
        "buyer_email": buyer_email,
        "buyer_phone": f"+53{customer_phone}",
        "status": status,
        "items": [{
            "product_id": str(product_id),
            "name": product_name,
            "quantity": 1,
            "unit_price": line_total,
            "currency": "CUP",
            "line_total": line_total,
        }],
        "subtotals": [{"currency": "CUP", "amount": line_total}],
        "delivery_requested": False,
        "payment_method": "contact",
        "payment_currency": "CUP",
        "created_at": now,
        "updated_at": now,
        "completed_at": now if status == "completed" else None,
        MARKER: True,
    })
    return {
        "customer_id": str(customer_id),
        "customer_phone": customer_phone,
        "full_name": buyer_name,
        "buyer_email": buyer_email,
        "buyer_phone": f"+53{customer_phone}",
        "seller_id": str(seller_id),
        "store_name": store_name,
        "product_id": str(product_id),
        "product_name": product_name,
        "order_id": str(order_id),
        "gestor_id": str(gestor_id),
        "line_total": str(line_total),
    }


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class AccountDeletionE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        run_db(cleanup)

    def tearDown(self) -> None:
        run_db(cleanup)

    def test_customer_delete_keeps_order_available_for_store(self) -> None:
        pair = run_db(lambda: seed_order_pair(status="completed"))
        customer_headers = customer_auth_headers(
            customer_id=pair["customer_id"],
            full_name=pair["full_name"],
        )
        seller_headers = seller_auth_headers(
            seller_id=pair["seller_id"],
            store_name=pair["store_name"],
        )

        with api_client() as client, patch(
            "app.customer_accounts.services.remove_image",
            new_callable=AsyncMock,
        ):
            before = client.get("/api/auth/me/orders", headers=seller_headers)
            self.assertEqual(before.status_code, 200, before.text)
            self.assertEqual(before.json()["total"], 1)

            deleted = client.delete("/api/customers/me", headers=customer_headers)
            self.assertEqual(deleted.status_code, 204, deleted.text)

            missing = client.get("/api/customers/me", headers=customer_headers)
            self.assertEqual(missing.status_code, 401, missing.text)

            seller_orders = client.get("/api/auth/me/orders", headers=seller_headers)
            self.assertEqual(seller_orders.status_code, 200, seller_orders.text)
            payload = seller_orders.json()
            self.assertEqual(payload["total"], 1)
            order = payload["items"][0]
            self.assertEqual(order["id"], pair["order_id"])
            self.assertEqual(order["store_name"], pair["store_name"])
            self.assertEqual(order["buyer_id"], pair["customer_id"])
            self.assertEqual(order["buyer_name"], pair["full_name"])
            self.assertEqual(order["buyer_email"], pair["buyer_email"])
            self.assertEqual(order["buyer_phone"], pair["buyer_phone"])
            self.assertEqual(order["status"], "completed")
            self.assertEqual(order["items"][0]["name"], pair["product_name"])
            self.assertEqual(order["items"][0]["line_total"], float(pair["line_total"]))

        async def assert_db() -> None:
            self.assertIsNone(
                await get_customers_collection().find_one({"_id": ObjectId(pair["customer_id"])})
            )
            self.assertEqual(
                await get_customer_notifications_collection().count_documents(
                    {"customer_id": ObjectId(pair["customer_id"])}
                ),
                0,
            )
            order = await get_orders_collection().find_one({"_id": ObjectId(pair["order_id"])})
            self.assertIsNotNone(order)
            self.assertEqual(order["buyer_name"], pair["full_name"])
            self.assertEqual(order["buyer_phone"], pair["buyer_phone"])

        run_db(assert_db)

    def test_seller_delete_keeps_order_available_for_customer(self) -> None:
        pair = run_db(lambda: seed_order_pair(status="completed"))
        customer_headers = customer_auth_headers(
            customer_id=pair["customer_id"],
            full_name=pair["full_name"],
        )
        seller_headers = seller_auth_headers(
            seller_id=pair["seller_id"],
            store_name=pair["store_name"],
        )

        with api_client() as client, patch(
            "app.services.seller_deletion.remove_image",
            new_callable=AsyncMock,
        ):
            before = client.get("/api/customers/me/orders", headers=customer_headers)
            self.assertEqual(before.status_code, 200, before.text)
            self.assertEqual(len(before.json()), 1)

            deleted = client.delete("/api/auth/me", headers=seller_headers)
            self.assertEqual(deleted.status_code, 204, deleted.text)

            missing = client.get("/api/auth/me", headers=seller_headers)
            self.assertIn(missing.status_code, {401, 404}, missing.text)

            customer_orders = client.get("/api/customers/me/orders", headers=customer_headers)
            self.assertEqual(customer_orders.status_code, 200, customer_orders.text)
            orders = customer_orders.json()
            self.assertEqual(len(orders), 1)
            order = orders[0]
            self.assertEqual(order["id"], pair["order_id"])
            self.assertEqual(order["store_id"], pair["seller_id"])
            self.assertEqual(order["store_name"], pair["store_name"])
            self.assertEqual(order["status"], "completed")
            self.assertEqual(order["items"][0]["name"], pair["product_name"])
            self.assertEqual(order["items"][0]["product_id"], pair["product_id"])
            self.assertEqual(order["items"][0]["unit_price"], float(pair["line_total"]))

        async def assert_db() -> None:
            self.assertIsNone(
                await get_registrations_collection().find_one({"_id": ObjectId(pair["seller_id"])})
            )
            self.assertEqual(
                await get_catalog_products_collection().count_documents(
                    {"_id": ObjectId(pair["product_id"])}
                ),
                0,
            )
            self.assertEqual(
                await get_gestores_collection().count_documents({"_id": ObjectId(pair["gestor_id"])}),
                0,
            )
            order = await get_orders_collection().find_one({"_id": ObjectId(pair["order_id"])})
            self.assertIsNotNone(order)
            self.assertEqual(order["store_name"], pair["store_name"])
            self.assertNotIn("deleted_at", order)

        run_db(assert_db)

    def test_customer_delete_blocked_when_order_pending(self) -> None:
        pair = run_db(lambda: seed_order_pair(status="pending_confirmation"))
        headers = customer_auth_headers(
            customer_id=pair["customer_id"],
            full_name=pair["full_name"],
        )
        with api_client() as client:
            blocked = client.delete("/api/customers/me", headers=headers)
            self.assertEqual(blocked.status_code, 400, blocked.text)
            self.assertIn("pendientes", blocked.json()["detail"].lower())

        async def assert_db() -> None:
            self.assertIsNotNone(
                await get_customers_collection().find_one({"_id": ObjectId(pair["customer_id"])})
            )
            order = await get_orders_collection().find_one({"_id": ObjectId(pair["order_id"])})
            self.assertEqual(order["status"], "pending_confirmation")

        run_db(assert_db)

    def test_seller_delete_blocked_when_order_pending(self) -> None:
        pair = run_db(lambda: seed_order_pair(status="pending_confirmation"))
        headers = seller_auth_headers(
            seller_id=pair["seller_id"],
            store_name=pair["store_name"],
        )
        with api_client() as client:
            blocked = client.delete("/api/auth/me", headers=headers)
            self.assertEqual(blocked.status_code, 400, blocked.text)
            self.assertIn("pendientes", blocked.json()["detail"].lower())

        async def assert_db() -> None:
            self.assertIsNotNone(
                await get_registrations_collection().find_one({"_id": ObjectId(pair["seller_id"])})
            )
            self.assertEqual(
                await get_catalog_products_collection().count_documents(
                    {"_id": ObjectId(pair["product_id"])}
                ),
                1,
            )

        run_db(assert_db)


if __name__ == "__main__":
    unittest.main()
