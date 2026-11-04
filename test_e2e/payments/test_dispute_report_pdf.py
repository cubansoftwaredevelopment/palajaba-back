"""Cada condición aceptada en el pedido sale en su propio PDF."""

from __future__ import annotations

import unittest
from datetime import datetime

from bson import ObjectId

from app.payments.dispute_report import build_agreement_pdf, build_evidence_pdf


class DisputeReportPdfTests(unittest.TestCase):
    def test_terms_and_delivery_policy_are_separate_pdfs(self) -> None:
        order = {
            "_id": ObjectId(),
            "store_agreements": {
                "terms": {
                    "accepted_at": datetime(2026, 11, 3, 17, 0),
                    "content": {
                        "type": "doc",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "El pago se acuerda con la tienda."}]}],
                    },
                },
                "delivery_policy": {
                    "accepted_at": datetime(2026, 11, 3, 17, 0),
                    "content": {
                        "type": "doc",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Entregamos de lunes a viernes."}]}],
                    },
                },
            },
        }

        terms_pdf, terms_name = build_agreement_pdf(order, "terms", store_name="startup")
        policy_pdf, policy_name = build_agreement_pdf(order, "delivery_policy", store_name="startup")

        self.assertTrue(terms_pdf.startswith(b"%PDF"))
        self.assertTrue(policy_pdf.startswith(b"%PDF"))
        self.assertIn(b"El pago se acuerda con la tienda.", terms_pdf)
        self.assertNotIn(b"Entregamos de lunes a viernes.", terms_pdf)
        self.assertIn(b"Entregamos de lunes a viernes.", policy_pdf)
        self.assertNotIn(b"El pago se acuerda con la tienda.", policy_pdf)
        self.assertTrue(terms_name.startswith("terminos-"))
        self.assertTrue(policy_name.startswith("politica-de-entrega-"))

    def test_evidence_pdf_contains_the_delivery_note(self) -> None:
        order_id = ObjectId()
        order = {
            "_id": order_id,
            "qvapay": {
                "evidence": {
                    "sent_at": datetime(2026, 11, 3, 18, 0),
                    "content": {
                        "type": "doc",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Dejé el pedido en recepción."}]}],
                    },
                },
            },
        }

        pdf, name = build_evidence_pdf(order, store_name="startup")

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"Dej\\351 el pedido en recepci\\363n.", pdf)
        self.assertEqual(name, f"evidencia-{str(order_id)[-6:].upper()}.pdf")
