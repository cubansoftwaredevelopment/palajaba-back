"""
Tests de optimización de imágenes (Cloudinary).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\test_media_storage.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.media_storage import _cloudinary_incoming_transformation


class CloudinaryIncomingTransformationTests(unittest.TestCase):
    def test_product_upload_limits_size_and_compresses(self) -> None:
        transforms = _cloudinary_incoming_transformation("products")
        self.assertEqual(
            transforms,
            [
                {"width": 1600, "height": 1600, "crop": "limit"},
                {"quality": "auto:good"},
                {"fetch_format": "auto"},
            ],
        )

    def test_profile_upload_uses_smaller_limit(self) -> None:
        transforms = _cloudinary_incoming_transformation("profiles")
        self.assertEqual(transforms[0]["width"], 800)
        self.assertEqual(transforms[0]["height"], 800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
