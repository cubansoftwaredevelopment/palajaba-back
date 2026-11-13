"""Cliente HTTP y autenticación de vendedor para tests e2e."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from starlette.testclient import TestClient

from app.main import app
from app.auth.utils import create_admin_token, create_customer_token, create_seller_token


@contextmanager
def api_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def seller_auth_headers(*, seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}


def customer_auth_headers(*, customer_id: str, full_name: str = "Cliente E2E") -> dict[str, str]:
    token = create_customer_token(customer_id=customer_id, full_name=full_name)
    return {"Authorization": f"Bearer {token}"}


def admin_auth_headers() -> dict[str, str]:
    token = create_admin_token(username="stats-e2e", admin_id="stats-e2e")
    return {"Authorization": f"Bearer {token}"}
