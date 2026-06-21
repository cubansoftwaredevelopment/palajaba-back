from __future__ import annotations

import os
import unittest
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import HTTPException
from starlette.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

from app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_registrations_collection,
    get_seller_feedback_collection,
)
from app.main import app
from app.schemas.seller_feedback import SellerFeedbackCreate
from app.security import create_admin_token, create_seller_token
from app.services.seller_feedback import (
    delete_admin_feedback,
    get_admin_feedback_unread_count,
    list_admin_feedback,
    mark_admin_feedback_read,
    submit_seller_feedback,
)
from tests.helpers_seller_feedback import (
    COMPLAINT_MESSAGE,
    MARKER,
    SUGGESTION_MESSAGE,
    feedback_document,
    seller_document,
)


def mongo_configured() -> bool:
    return bool(os.getenv("MONGODB_URL", "").strip())


class FeedbackSeed:
    seller_id: str
    seller_oid: ObjectId
    complaint_id: ObjectId
    suggestion_id: ObjectId
    read_suggestion_id: ObjectId


async def cleanup_feedback_test_data() -> None:
    feedback = get_seller_feedback_collection()
    registrations = get_registrations_collection()
    await feedback.delete_many({"seller_feedback_test_marker": MARKER})
    await registrations.delete_many({"seller_feedback_test_marker": MARKER})


async def seed_feedback_test_data() -> FeedbackSeed:
    seed = FeedbackSeed()
    seed.seller_oid = ObjectId()
    seed.seller_id = str(seed.seller_oid)
    seed.complaint_id = ObjectId()
    seed.suggestion_id = ObjectId()
    seed.read_suggestion_id = ObjectId()

    registrations = get_registrations_collection()
    feedback = get_seller_feedback_collection()

    await registrations.insert_one(seller_document(seed.seller_oid))
    await feedback.insert_one(
        feedback_document(
            seller_id=seed.seller_oid,
            feedback_id=seed.complaint_id,
            feedback_type="complaint",
            message=COMPLAINT_MESSAGE,
        )
    )
    await feedback.insert_one(
        feedback_document(
            seller_id=seed.seller_oid,
            feedback_id=seed.suggestion_id,
            feedback_type="suggestion",
            message=SUGGESTION_MESSAGE,
        )
    )
    from app.utils.datetime import to_utc_naive, utc_now

    await feedback.insert_one(
        feedback_document(
            seller_id=seed.seller_oid,
            feedback_id=seed.read_suggestion_id,
            feedback_type="suggestion",
            message="Sugerencia ya leída por el administrador.",
            read_at=to_utc_naive(utc_now()),
        )
    )
    return seed


def seller_auth_header(seller_id: str, store_name: str) -> dict[str, str]:
    token = create_seller_token(seller_id=seller_id, store_name=store_name)
    return {"Authorization": f"Bearer {token}"}


def admin_auth_header() -> dict[str, str]:
    token = create_admin_token(username="test-admin", admin_id=str(ObjectId()))
    return {"Authorization": f"Bearer {token}"}


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SellerFeedbackServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    seed: FeedbackSeed

    async def asyncSetUp(self) -> None:
        await connect_to_mongo()
        await cleanup_feedback_test_data()
        self.seed = await seed_feedback_test_data()

    async def asyncTearDown(self) -> None:
        await cleanup_feedback_test_data()
        await close_mongo_connection()

    async def test_submit_creates_unread_feedback(self) -> None:
        payload = SellerFeedbackCreate(
            feedback_type="complaint",
            message="Nuevo mensaje enviado desde integración.",
        )
        result = await submit_seller_feedback(self.seed.seller_id, payload)
        self.assertTrue(result.id)

        doc = await get_seller_feedback_collection().find_one({"_id": ObjectId(result.id)})
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertIsNone(doc.get("read_at"))
        self.assertEqual(doc["feedback_type"], "complaint")

    async def test_submit_rejects_unknown_seller(self) -> None:
        payload = SellerFeedbackCreate(
            feedback_type="suggestion",
            message="Mensaje para vendedor inexistente.",
        )
        with self.assertRaises(HTTPException) as ctx:
            await submit_seller_feedback(str(ObjectId()), payload)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_list_all_includes_seeded_feedback(self) -> None:
        items = await list_admin_feedback(feedback_filter="all")
        ids = {item.id for item in items}
        self.assertIn(str(self.seed.complaint_id), ids)
        self.assertIn(str(self.seed.suggestion_id), ids)
        self.assertIn(str(self.seed.read_suggestion_id), ids)

    async def test_list_unread_excludes_read_items(self) -> None:
        items = await list_admin_feedback(feedback_filter="unread")
        ids = {item.id for item in items}
        self.assertIn(str(self.seed.complaint_id), ids)
        self.assertIn(str(self.seed.suggestion_id), ids)
        self.assertNotIn(str(self.seed.read_suggestion_id), ids)

    async def test_list_complaint_filter(self) -> None:
        items = await list_admin_feedback(feedback_filter="complaint")
        self.assertTrue(all(item.feedback_type == "complaint" for item in items))
        self.assertIn(str(self.seed.complaint_id), {item.id for item in items})

    async def test_list_suggestion_filter(self) -> None:
        items = await list_admin_feedback(feedback_filter="suggestion")
        self.assertTrue(all(item.feedback_type == "suggestion" for item in items))
        ids = {item.id for item in items}
        self.assertIn(str(self.seed.suggestion_id), ids)
        self.assertIn(str(self.seed.read_suggestion_id), ids)

    async def test_unread_count_matches_unread_documents(self) -> None:
        count = await get_admin_feedback_unread_count()
        self.assertGreaterEqual(count.unread_count, 2)

    async def test_mark_read_sets_read_at(self) -> None:
        updated = await mark_admin_feedback_read(str(self.seed.complaint_id))
        self.assertIsNotNone(updated.read_at)
        doc = await get_seller_feedback_collection().find_one({"_id": self.seed.complaint_id})
        assert doc is not None
        self.assertIsNotNone(doc.get("read_at"))

    async def test_mark_read_is_idempotent(self) -> None:
        first = await mark_admin_feedback_read(str(self.seed.suggestion_id))
        doc_after_first = await get_seller_feedback_collection().find_one(
            {"_id": self.seed.suggestion_id}
        )
        second = await mark_admin_feedback_read(str(self.seed.suggestion_id))
        doc_after_second = await get_seller_feedback_collection().find_one(
            {"_id": self.seed.suggestion_id}
        )
        self.assertIsNotNone(first.read_at)
        self.assertIsNotNone(second.read_at)
        assert doc_after_first is not None and doc_after_second is not None
        self.assertEqual(doc_after_first.get("read_at"), doc_after_second.get("read_at"))

    async def test_delete_removes_feedback(self) -> None:
        result = await delete_admin_feedback(str(self.seed.complaint_id))
        self.assertEqual(result.id, str(self.seed.complaint_id))
        doc = await get_seller_feedback_collection().find_one({"_id": self.seed.complaint_id})
        self.assertIsNone(doc)

    async def test_delete_unknown_feedback_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await delete_admin_feedback(str(ObjectId()))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_mark_read_unknown_feedback_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await mark_admin_feedback_read(str(ObjectId()))
        self.assertEqual(ctx.exception.status_code, 404)


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class SellerFeedbackApiIntegrationTests(unittest.TestCase):
    seed: FeedbackSeed

    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        async def prepare() -> FeedbackSeed:
            await connect_to_mongo()
            await cleanup_feedback_test_data()
            return await seed_feedback_test_data()

        cls.seed = asyncio.run(prepare())

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio

        async def finalize() -> None:
            await connect_to_mongo()
            await cleanup_feedback_test_data()
            await close_mongo_connection()

        asyncio.run(finalize())

    def test_seller_post_feedback_returns_201(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/me/feedback",
                headers=seller_auth_header(self.seed.seller_id, "TEST Seller Feedback Store"),
                json={
                    "feedback_type": "suggestion",
                    "message": "Mensaje HTTP de integración suficiente.",
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertIn("id", payload)
        self.assertIn("message", payload)

    def test_seller_post_without_auth_returns_401(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/me/feedback",
                json={
                    "feedback_type": "complaint",
                    "message": "Mensaje sin autenticación.",
                },
            )
        self.assertEqual(response.status_code, 401)

    def test_seller_post_short_message_returns_422(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/me/feedback",
                headers=seller_auth_header(self.seed.seller_id, "TEST Seller Feedback Store"),
                json={"feedback_type": "complaint", "message": "corto"},
            )
        self.assertEqual(response.status_code, 422)

    def test_admin_list_feedback_returns_200(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/feedback",
                headers=admin_auth_header(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreaterEqual(len(response.json()), 3)

    def test_admin_list_unread_filter(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/feedback?filter=unread",
                headers=admin_auth_header(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(all(item["read_at"] is None for item in payload))

    def test_admin_unread_count_endpoint(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/feedback/unread-count",
                headers=admin_auth_header(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("unread_count", response.json())

    def test_admin_mark_read_endpoint(self) -> None:
        with TestClient(app) as client:
            response = client.patch(
                f"/api/admin/feedback/{self.seed.suggestion_id}/read",
                headers=admin_auth_header(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json().get("read_at"))

    def test_admin_delete_feedback_endpoint(self) -> None:
        import asyncio

        async def insert_extra() -> ObjectId:
            await connect_to_mongo()
            oid = ObjectId()
            await get_seller_feedback_collection().insert_one(
                feedback_document(
                    seller_id=self.seed.seller_oid,
                    feedback_id=oid,
                    feedback_type="complaint",
                    message="Mensaje temporal para borrar por HTTP.",
                )
            )
            return oid

        extra_id = asyncio.run(insert_extra())
        with TestClient(app) as client:
            response = client.delete(
                f"/api/admin/feedback/{extra_id}",
                headers=admin_auth_header(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json().get("id"), str(extra_id))

    def test_admin_endpoints_without_auth_return_401(self) -> None:
        with TestClient(app) as client:
            list_response = client.get("/api/admin/feedback")
            delete_response = client.delete(f"/api/admin/feedback/{self.seed.complaint_id}")
        self.assertEqual(list_response.status_code, 401)
        self.assertEqual(delete_response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
