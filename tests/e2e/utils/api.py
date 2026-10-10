"""Cliente HTTP y autenticación de vendedor para tests e2e."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from starlette.testclient import TestClient

from app.main import app
from app.security import create_seller_token


@contextmanager
def api_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def seller_auth_headers(*, seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}
