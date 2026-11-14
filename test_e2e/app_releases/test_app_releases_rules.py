"""Reglas de builds de app: main único, no borrar main, tope de 5."""

from __future__ import annotations

import unittest
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
            "gridfs_id": ObjectId(),
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
            patch("app.live.push.notify_app_update_devices", AsyncMock()) as notify_mock,
        ):
            result = await service.set_main_release(str(release_id))
        collection.update_many.assert_awaited()
        collection.update_one.assert_awaited()
        notify_mock.assert_awaited_once_with(platform="ios", version="2.0.0")
        self.assertTrue(result.is_main)
        self.assertEqual(result.version, "2.0.0")

    async def test_set_main_skips_notify_when_already_main(self):
        release_id = ObjectId()
        doc = {
            "_id": release_id,
            "platform": "android",
            "version": "1.0.1",
            "is_main": True,
            "original_filename": "app.apk",
            "size_bytes": 10,
            "uploaded_at": None,
        }
        collection = MagicMock()
        collection.update_many = AsyncMock()
        collection.update_one = AsyncMock()
        collection.find_one = AsyncMock(return_value=doc)
        with (
            patch.object(service, "_get_release_or_404", AsyncMock(return_value=doc)),
            patch("app.app_releases.service.get_app_releases_collection", return_value=collection),
            patch("app.live.push.notify_app_update_devices", AsyncMock()) as notify_mock,
        ):
            result = await service.set_main_release(str(release_id))
        collection.update_many.assert_not_awaited()
        collection.update_one.assert_not_awaited()
        notify_mock.assert_not_awaited()
        self.assertTrue(result.is_main)

    async def test_trim_keeps_main_and_max_five(self):
        main_id = ObjectId()
        docs = [
            {"_id": ObjectId(), "is_main": False, "gridfs_id": ObjectId()}
            for _ in range(5)
        ]
        docs.insert(0, {"_id": main_id, "is_main": True, "gridfs_id": ObjectId()})
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
            patch.object(service, "_delete_release_binary", AsyncMock()),
        ):
            await service._trim_platform_history("android")

        self.assertEqual(len(remaining), 5)
        self.assertTrue(any(doc["_id"] == main_id for doc in remaining))

    async def test_store_app_file_uses_gridfs(self):
        content = b"fake-apk-bytes"
        grid_id = ObjectId()
        bucket = MagicMock()
        bucket.upload_from_stream = AsyncMock(return_value=grid_id)
        with patch("app.app_releases.service.get_app_release_gridfs", return_value=bucket):
            result = await service._store_app_file(
                "android",
                content,
                "PaLaJaba.apk",
                "application/vnd.android.package-archive",
            )
        self.assertEqual(result, grid_id)
        bucket.upload_from_stream.assert_awaited_once()
        args, kwargs = bucket.upload_from_stream.await_args
        self.assertTrue(str(args[0]).endswith(".apk"))
        self.assertEqual(kwargs["metadata"]["platform"], "android")
        self.assertEqual(kwargs["metadata"]["original_filename"], "PaLaJaba.apk")

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
