"""Reglas de builds de app: main único, no borrar main, tope de 5."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.app_releases import service


class AppReleaseRulesTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_version_rejects_empty(self):
        with self.assertRaises(HTTPException) as ctx:
            service._normalize_version("  ")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_normalize_platform(self):
        self.assertEqual(service._normalize_platform("Android"), "android")
        with self.assertRaises(HTTPException):
            service._normalize_platform("windows")

    async def test_delete_main_blocked(self):
        doc = {
            "_id": ObjectId(),
            "platform": "android",
            "version": "1.0.0",
            "is_main": True,
            "file_path": "app-releases/android/x.apk",
        }
        with patch.object(service, "_get_release_or_404", AsyncMock(return_value=doc)):
            with self.assertRaises(HTTPException) as ctx:
                await service.delete_release(str(doc["_id"]))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("principal", ctx.exception.detail)

    async def test_set_main_clears_previous(self):
        release_id = ObjectId()
        doc = {
            "_id": release_id,
            "platform": "ios",
            "version": "2.0.0",
            "is_main": False,
            "original_filename": "app.ipa",
            "size_bytes": 10,
            "uploaded_at": None,
        }
        collection = MagicMock()
        collection.update_many = AsyncMock()
        collection.update_one = AsyncMock()
        collection.find_one = AsyncMock(
            side_effect=[
                {**doc, "is_main": True},
            ]
        )
        with (
            patch.object(service, "_get_release_or_404", AsyncMock(return_value=doc)),
            patch("app.app_releases.service.get_app_releases_collection", return_value=collection),
        ):
            result = await service.set_main_release(str(release_id))
        collection.update_many.assert_awaited()
        collection.update_one.assert_awaited()
        self.assertTrue(result.is_main)
        self.assertEqual(result.version, "2.0.0")

    async def test_trim_keeps_main_and_max_five(self):
        main_id = ObjectId()
        docs = [
            {"_id": ObjectId(), "is_main": False, "file_path": f"a{i}.apk"}
            for i in range(5)
        ]
        docs.insert(0, {"_id": main_id, "is_main": True, "file_path": "main.apk"})
        remaining = list(docs)

        class Cursor:
            def __init__(self, items):
                self._items = items

            def sort(self, *_args, **_kwargs):
                return self

            async def to_list(self, length=None):
                return list(self._items)

        collection = MagicMock()
        collection.find = MagicMock(side_effect=lambda *_a, **_k: Cursor(remaining))

        async def delete_one(query):
            oid = query["_id"]
            remaining[:] = [doc for doc in remaining if doc["_id"] != oid]

        collection.delete_one = AsyncMock(side_effect=delete_one)

        with (
            patch("app.app_releases.service.get_app_releases_collection", return_value=collection),
            patch.object(service, "_delete_file", AsyncMock()),
        ):
            await service._trim_platform_history("android")

        self.assertEqual(len(remaining), 5)
        self.assertTrue(any(doc["_id"] == main_id for doc in remaining))

    async def test_store_and_stream_roundtrip_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = b"fake-apk-bytes"
            with patch.object(service, "UPLOADS_ROOT", root):
                relative, path = service._store_app_file("android", content, "PaLaJaba.apk")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), content)
            self.assertTrue(relative.startswith("app-releases/android/"))

    def test_platform_prompt_status_needs_download(self):
        main = {
            "_id": ObjectId(),
            "platform": "android",
            "version": "1.0.1",
            "original_filename": "a.apk",
            "size_bytes": 10,
            "is_main": True,
            "uploaded_at": None,
        }
        missing = service._platform_prompt_status(main, None)
        self.assertTrue(missing.needs_download)
        self.assertIsNone(missing.downloaded_version)

        outdated = service._platform_prompt_status(main, {"version": "1.0.0"})
        self.assertTrue(outdated.needs_download)

        current = service._platform_prompt_status(main, {"version": "1.0.1"})
        self.assertFalse(current.needs_download)


if __name__ == "__main__":
    unittest.main()
