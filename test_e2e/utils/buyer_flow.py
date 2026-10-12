"""Recorrido de comprador: vista, jaba, pedido y cierre."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from test_e2e.utils.api import api_client


def complete_marketplace_order(
    test: unittest.TestCase,
    *,
    product_id: str,
    order_body: dict,
    seller_headers: dict[str, str],
) -> None:
    with api_client() as client, patch(
        "app.services.orders.notification_service.notify_seller_new_order",
        new_callable=AsyncMock,
    ):
        view = client.post(
            f"/api/marketplace/products/{product_id}/popularity",
            json={"event": "view"},
        )
        test.assertEqual(view.status_code, 204, view.text)

        jaba = client.post(
            f"/api/marketplace/products/{product_id}/popularity",
            json={"event": "jaba"},
        )
        test.assertEqual(jaba.status_code, 204, jaba.text)

        created = client.post("/api/marketplace/orders", json=order_body)
        test.assertEqual(created.status_code, 201, created.text)

        completed = client.patch(
            f"/api/auth/me/orders/{created.json()['id']}",
            headers=seller_headers,
            json={"status": "completed", "payment_currency": "CUP"},
        )
        test.assertEqual(completed.status_code, 200, completed.text)
        test.assertEqual(completed.json()["status"], "completed")
