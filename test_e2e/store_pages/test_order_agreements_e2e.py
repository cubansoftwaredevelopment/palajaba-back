"""La compra guarda la política y los términos que el cliente acepta."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.auth.utils import create_customer_token
from app.database import get_customers_collection, get_orders_collection, get_registrations_collection
from test_e2e.store_pages.utils.fixtures import MARKER, cleanup, headers_for, seed_seller
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured, run_db


def _doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def cleanup_agreements() -> None:
    sellers = await get_registrations_collection().find(
        {"store_pages_e2e_marker": MARKER},
        {"_id": 1},
    ).to_list(length=None)
    seller_ids = [str(doc["_id"]) for doc in sellers]
    if seller_ids:
        await get_orders_collection().delete_many({"seller_id": {"$in": seller_ids}})
    await get_customers_collection().delete_many({"store_pages_e2e_marker": MARKER})
    await cleanup()


async def seed_customer() -> str:
    customer_id = ObjectId()
    await get_customers_collection().insert_one(
        {
            "_id": customer_id,
            "full_name": "Cliente Políticas",
            "email": f"politicas-{customer_id}@example.com",
            "phone": f"{int(str(customer_id), 16) % 90000000 + 10000000:08d}",
            "store_pages_e2e_marker": MARKER,
        }
    )
    return str(customer_id)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class OrderAgreementsE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_db(cleanup_agreements)

    @classmethod
    def tearDownClass(cls) -> None:
        run_db(cleanup_agreements)

    def test_purchase_requires_and_stores_configured_pages(self) -> None:
        seller = seed_seller()
        customer_id = run_db(seed_customer)
        headers = {"Authorization": f"Bearer {create_customer_token(customer_id=customer_id, full_name='Cliente Políticas')}"}
        policy = _doc("Entregamos de lunes a viernes.")
        terms = _doc("El pago se acuerda con la tienda.")
        order_body = {
            "store_id": seller["seller_id"],
            "items": [{
                "product_id": str(ObjectId()),
                "name": "Arroz",
                "quantity": 1,
                "unit_price": 10,
                "currency": "CUP",
            }],
            "payment_currency": "CUP",
        }

        with api_client() as client, patch(
            "app.orders.service.notification_service.notify_seller_new_order",
            new_callable=AsyncMock,
        ):
            for page, content in (("delivery_policy", policy), ("terms", terms)):
                saved = client.patch(
                    "/api/auth/me/store-pages",
                    headers=headers_for(seller),
                    json={"page": page, "content": content},
                )
                self.assertEqual(saved.status_code, 200, saved.text)

            store = client.get(f"/api/marketplace/stores/{seller['store_slug']}")
            self.assertEqual(store.status_code, 200, store.text)
            self.assertTrue(store.json()["store_pages"]["delivery_policy"])
            self.assertTrue(store.json()["store_pages"]["terms"])

            contact = client.post("/api/marketplace/orders", headers=headers, json=order_body)
            self.assertEqual(contact.status_code, 201, contact.text)
            self.assertIsNone(contact.json()["store_agreements"])

            qvapay_body = {**order_body, "payment_method": "qvapay"}
            missing = client.post("/api/marketplace/orders", headers=headers, json=qvapay_body)
            self.assertEqual(missing.status_code, 400, missing.text)
            self.assertIn("política de entrega", missing.json()["detail"])

            only_policy = client.post(
                "/api/marketplace/orders",
                headers=headers,
                json={**qvapay_body, "accepted_delivery_policy": True},
            )
            self.assertEqual(only_policy.status_code, 400, only_policy.text)
            self.assertIn("términos", only_policy.json()["detail"])

            created = client.post(
                "/api/marketplace/orders",
                headers=headers,
                json={**order_body, "accepted_delivery_policy": True, "accepted_terms": True},
            )
            self.assertEqual(created.status_code, 201, created.text)
            agreements = created.json()["store_agreements"]
            self.assertEqual(agreements["delivery_policy"]["content"], policy)
            self.assertEqual(agreements["terms"]["content"], terms)
            self.assertEqual(agreements["delivery_policy"]["title"], "Política de entrega")
            self.assertTrue(agreements["terms"]["accepted_at"])
