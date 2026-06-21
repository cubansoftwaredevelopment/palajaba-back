from __future__ import annotations

import unittest
from datetime import datetime, timezone

from bson import ObjectId
from pydantic import ValidationError

from app.schemas.seller_feedback import SellerFeedbackCreate
from app.services.seller_feedback import _build_admin_list_query, _document_to_public


class SellerFeedbackCreateSchemaTests(unittest.TestCase):
    def test_accepts_valid_suggestion(self) -> None:
        payload = SellerFeedbackCreate(
            feedback_type="suggestion",
            message="Me gustaría ver más filtros en el catálogo.",
        )
        self.assertEqual(payload.feedback_type, "suggestion")
        self.assertIn("filtros", payload.message)

    def test_accepts_valid_complaint(self) -> None:
        payload = SellerFeedbackCreate(
            feedback_type="complaint",
            message="Tuve un problema al subir fotos de productos.",
        )
        self.assertEqual(payload.feedback_type, "complaint")

    def test_strips_surrounding_whitespace(self) -> None:
        payload = SellerFeedbackCreate(
            feedback_type="suggestion",
            message="   Mensaje válido con espacios   ",
        )
        self.assertEqual(payload.message, "Mensaje válido con espacios")

    def test_rejects_message_shorter_than_ten_characters(self) -> None:
        with self.assertRaises(ValidationError):
            SellerFeedbackCreate(feedback_type="complaint", message="corto")

    def test_rejects_whitespace_only_message(self) -> None:
        with self.assertRaises(ValidationError):
            SellerFeedbackCreate(feedback_type="suggestion", message="          ")

    def test_rejects_message_over_two_thousand_characters(self) -> None:
        with self.assertRaises(ValidationError):
            SellerFeedbackCreate(
                feedback_type="complaint",
                message="x" * 2001,
            )

    def test_accepts_message_with_exactly_ten_characters(self) -> None:
        payload = SellerFeedbackCreate(
            feedback_type="suggestion",
            message="1234567890",
        )
        self.assertEqual(len(payload.message), 10)

    def test_rejects_invalid_feedback_type(self) -> None:
        with self.assertRaises(ValidationError):
            SellerFeedbackCreate(
                feedback_type="other",
                message="Mensaje válido de prueba.",
            )


class BuildAdminListQueryTests(unittest.TestCase):
    def test_all_filter_returns_empty_query(self) -> None:
        self.assertEqual(_build_admin_list_query(feedback_filter="all"), {})

    def test_unread_filter_matches_null_read_at(self) -> None:
        self.assertEqual(
            _build_admin_list_query(feedback_filter="unread"),
            {"read_at": None},
        )

    def test_complaint_filter(self) -> None:
        self.assertEqual(
            _build_admin_list_query(feedback_filter="complaint"),
            {"feedback_type": "complaint"},
        )

    def test_suggestion_filter(self) -> None:
        self.assertEqual(
            _build_admin_list_query(feedback_filter="suggestion"),
            {"feedback_type": "suggestion"},
        )


class DocumentToPublicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        self.seller_oid = ObjectId()
        self.feedback_oid = ObjectId()

    def test_maps_unread_feedback_fields(self) -> None:
        doc = {
            "_id": self.feedback_oid,
            "seller_id": self.seller_oid,
            "store_name": "Joyería R",
            "store_slug": "r-jewelry",
            "feedback_type": "complaint",
            "message": "No veo mis productos en el catálogo.",
            "read_at": None,
            "created_at": self.now,
        }
        public = _document_to_public(doc)
        self.assertEqual(public.id, str(self.feedback_oid))
        self.assertEqual(public.seller_id, str(self.seller_oid))
        self.assertEqual(public.store_name, "Joyería R")
        self.assertEqual(public.store_slug, "r-jewelry")
        self.assertEqual(public.feedback_type, "complaint")
        self.assertIsNone(public.read_at)

    def test_maps_read_feedback_with_timestamp(self) -> None:
        doc = {
            "_id": self.feedback_oid,
            "seller_id": self.seller_oid,
            "store_name": "Tienda",
            "store_slug": "tienda",
            "feedback_type": "suggestion",
            "message": "Agreguen exportación de pedidos por favor.",
            "read_at": self.now,
            "created_at": self.now,
        }
        public = _document_to_public(doc)
        self.assertIsNotNone(public.read_at)

    def test_allows_missing_store_slug(self) -> None:
        doc = {
            "_id": self.feedback_oid,
            "seller_id": self.seller_oid,
            "store_name": "Tienda",
            "feedback_type": "suggestion",
            "message": "Mensaje de prueba suficientemente largo.",
            "read_at": None,
            "created_at": self.now,
        }
        public = _document_to_public(doc)
        self.assertIsNone(public.store_slug)


if __name__ == "__main__":
    unittest.main()
