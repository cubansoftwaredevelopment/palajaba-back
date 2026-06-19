"""Unit tests for admin registration marketplace insights."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.admin_registration_insights import build_marketplace_visibility_notes


def _approved_doc(**overrides):
    now = datetime.utcnow()
    base = {
        "status": "approved",
        "profile_photo_url": "https://example.com/photo.jpg",
        "category_ids": ["food"],
        "offers_delivery": False,
        "business_area": {
            "province_id": "la-habana",
            "province_name": "La Habana",
            "municipality_id": "plaza",
            "municipality_name": "Plaza de la Revolución",
        },
        "subscription_starts_at": now - timedelta(days=5),
        "subscription_ends_at": now + timedelta(days=25),
        "delivery_areas": [],
    }
    base.update(overrides)
    return base


def test_notes_when_no_products():
    notes = build_marketplace_visibility_notes(_approved_doc(), {"total": 0, "published": 0})
    assert any("Sin productos" in note for note in notes)


def test_notes_when_products_not_published():
    notes = build_marketplace_visibility_notes(
        _approved_doc(),
        {"total": 4, "published": 0, "view_only": 2, "unavailable": 2},
    )
    assert any("ninguno publicado" in note for note in notes)
    assert any("solo vista" in note for note in notes)
    assert any("no disponibles" in note for note in notes)


def test_location_hint_when_published_products():
    notes = build_marketplace_visibility_notes(
        _approved_doc(offers_delivery=True, delivery_areas=[
            {
                "province_id": "matanzas",
                "province_name": "Matanzas",
                "municipality_id": "matanzas",
                "municipality_name": "Matanzas",
            }
        ]),
        {"total": 4, "published": 4},
    )
    assert any(note.startswith("Ubicación de la tienda") for note in notes)
    assert any("Matanzas" in note for note in notes)


def test_expired_status_note():
    doc = _approved_doc(status="expired")
    notes = build_marketplace_visibility_notes(doc, {"total": 4, "published": 4})
    assert notes == ["Suscripción vencida: la tienda no aparece en marketplace ni home."]


def main() -> None:
    test_notes_when_no_products()
    test_notes_when_products_not_published()
    test_location_hint_when_published_products()
    test_expired_status_note()
    print("OK: admin registration insights")


if __name__ == "__main__":
    main()
