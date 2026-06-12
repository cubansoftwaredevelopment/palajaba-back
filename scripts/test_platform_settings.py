"""Prueba rápida: settings admin y contacto público de renovación."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo
from app.security import create_admin_token

BASE_URL = "http://127.0.0.1:8081"


async def main() -> None:
    await connect_to_mongo()
    token = create_admin_token(username="admin", admin_id="000000000000000000000001")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        get_resp = await client.get(
            "/api/admin/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 200, get_resp.text

        patch_resp = await client.patch(
            "/api/admin/settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"renewal_contact_phone": "51234567"},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        public_resp = await client.get("/api/platform/renewal-contact")
        assert public_resp.status_code == 200, public_resp.text
        assert public_resp.json().get("renewal_contact_phone") == "51234567"

    await close_mongo_connection()
    print("OK: admin settings + renewal contact")


if __name__ == "__main__":
    asyncio.run(main())
