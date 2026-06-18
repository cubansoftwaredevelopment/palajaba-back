"""
Integración: optimización de imágenes con Cloudinary.

Verifica:
- store_image() envía incoming transformation al subir (productos y perfiles)
- remove_image() resuelve public_id desde URLs con transformaciones de entrega
- (opcional) subida real a Cloudinary si RUN_CLOUDINARY_LIVE_TEST=1

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_media_storage_integration.py

Subida real (requiere CLOUDINARY_* en .env):
  set RUN_CLOUDINARY_LIVE_TEST=1
  .\\venv\\Scripts\\python.exe scripts\\test_media_storage_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.datastructures import UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services import media_storage as media_storage_service
from app.services.media_storage import (
    _cloudinary_incoming_transformation,
    _public_id_from_url,
    read_image_upload,
    remove_image,
    store_image,
)

MINI_PNG = bytes(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)

SAMPLE_CLOUDINARY_URL = (
    "https://res.cloudinary.com/demo/image/upload/v1710000000/"
    "pala-jaba/products/seller1-abc123def456.jpg"
)
SAMPLE_OPTIMIZED_URL = (
    "https://res.cloudinary.com/demo/image/upload/f_auto,q_auto/v1710000000/"
    "pala-jaba/products/seller1-abc123def456.jpg"
)


def _mock_upload_result(*, scope: str, owner_id: str) -> dict:
    public_id = f"pala-jaba/{scope}/{owner_id}-mock123456"
    return {
        "secure_url": (
            f"https://res.cloudinary.com/demo/image/upload/v1710000000/{public_id}.jpg"
        ),
        "public_id": public_id,
        "width": 1600 if scope == "products" else 800,
        "height": 1200 if scope == "products" else 800,
        "bytes": 42_000,
        "format": "jpg",
    }


def _cloudinary_settings(enabled: bool):
    mock = MagicMock()
    mock.cloudinary_enabled = enabled
    return patch("app.services.media_storage.settings", mock)


class MediaStorageIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_image_products_sends_incoming_transformation(self) -> None:
        upload_mock = MagicMock(return_value=_mock_upload_result(scope="products", owner_id="seller1"))

        with (
            _cloudinary_settings(True),
            patch("app.services.media_storage.cloudinary.uploader.upload", upload_mock),
        ):
            stored = await store_image(
                MINI_PNG,
                "image/png",
                scope="products",
                owner_id="seller1",
            )

        upload_mock.assert_called_once()
        kwargs = upload_mock.call_args.kwargs
        self.assertEqual(kwargs["folder"], "pala-jaba/products")
        self.assertEqual(kwargs["resource_type"], "image")
        self.assertEqual(
            kwargs["transformation"],
            _cloudinary_incoming_transformation("products"),
        )
        self.assertTrue(stored.url.startswith("https://res.cloudinary.com/"))
        self.assertEqual(stored.public_id, "pala-jaba/products/seller1-mock123456")

    async def test_store_image_profiles_uses_profile_limits(self) -> None:
        upload_mock = MagicMock(return_value=_mock_upload_result(scope="profiles", owner_id="seller2"))

        with (
            _cloudinary_settings(True),
            patch("app.services.media_storage.cloudinary.uploader.upload", upload_mock),
        ):
            await store_image(
                MINI_PNG,
                "image/png",
                scope="profiles",
                owner_id="seller2",
            )

        kwargs = upload_mock.call_args.kwargs
        self.assertEqual(kwargs["folder"], "pala-jaba/profiles")
        self.assertEqual(
            kwargs["transformation"],
            _cloudinary_incoming_transformation("profiles"),
        )
        self.assertEqual(kwargs["transformation"][0]["width"], 800)

    async def test_read_image_upload_then_store_image_pipeline(self) -> None:
        upload = UploadFile(
            filename="producto.png",
            file=BytesIO(MINI_PNG),
            headers={"content-type": "image/png"},
        )
        content, content_type = await read_image_upload(upload)

        upload_mock = MagicMock(return_value=_mock_upload_result(scope="products", owner_id="seller3"))
        with (
            _cloudinary_settings(True),
            patch("app.services.media_storage.cloudinary.uploader.upload", upload_mock),
        ):
            stored = await store_image(
                content,
                content_type,
                scope="products",
                owner_id="seller3",
            )

        self.assertIn("transformation", upload_mock.call_args.kwargs)
        self.assertIsNotNone(stored.public_id)

    async def test_remove_image_accepts_delivery_optimized_url(self) -> None:
        destroy_mock = MagicMock()
        public_id = _public_id_from_url(SAMPLE_OPTIMIZED_URL)
        self.assertEqual(public_id, "pala-jaba/products/seller1-abc123def456")

        with (
            _cloudinary_settings(True),
            patch("app.services.media_storage.cloudinary.uploader.destroy", destroy_mock),
        ):
            await remove_image(SAMPLE_OPTIMIZED_URL)

        destroy_mock.assert_called_once_with(
            "pala-jaba/products/seller1-abc123def456",
            resource_type="image",
        )

    async def test_store_image_without_cloudinary_uses_local_path(self) -> None:
        owner_id = "local-seller"
        with _cloudinary_settings(False):
            stored = await store_image(
                MINI_PNG,
                "image/png",
                scope="products",
                owner_id=owner_id,
            )

        self.assertTrue(stored.url.startswith("/uploads/products/"))
        self.assertIsNone(stored.public_id)

        relative = stored.url.removeprefix("/uploads/")
        filepath = media_storage_service.LOCAL_UPLOADS_ROOT / relative
        self.assertTrue(filepath.is_file())
        filepath.unlink(missing_ok=True)


class CloudinaryLiveIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if os.getenv("RUN_CLOUDINARY_LIVE_TEST") != "1":
            self.skipTest("Define RUN_CLOUDINARY_LIVE_TEST=1 para subida real a Cloudinary.")
        if not settings.cloudinary_enabled:
            self.skipTest("CLOUDINARY_* no configurado en el entorno.")
        media_storage_service.init_cloudinary()

    async def test_live_upload_applies_incoming_transformation(self) -> None:
        owner_id = f"integration-{os.getpid()}"
        stored = await store_image(
            MINI_PNG,
            "image/png",
            scope="products",
            owner_id=owner_id,
        )

        self.assertTrue(stored.url.startswith("https://res.cloudinary.com/"))
        self.assertIsNotNone(stored.public_id)

        try:
            import httpx

            upload_idx = stored.url.find("/upload/")
            self.assertNotEqual(upload_idx, -1)
            delivery_url = (
                f"{stored.url[: upload_idx + len('/upload/')]}"
                f"f_auto,q_auto/{stored.url[upload_idx + len('/upload/'):]}"
            )

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(delivery_url)

            self.assertEqual(response.status_code, 200, response.text[:200])
            self.assertTrue(response.headers.get("content-type", "").startswith("image/"))
            self.assertGreater(len(response.content), 0)
        finally:
            if stored.public_id:
                await remove_image(stored.url, public_id=stored.public_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
