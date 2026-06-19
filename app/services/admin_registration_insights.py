from __future__ import annotations

from typing import Any

from app.database import get_catalog_products_collection
from app.services.seller_profile import is_profile_complete
from app.services.subscriptions import is_subscription_active

_EMPTY_COUNTS = {
    "total": 0,
    "published": 0,
    "view_only": 0,
    "unavailable": 0,
}


def _parse_business_area(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    required = ("province_id", "province_name", "municipality_id", "municipality_name")
    if not all(raw.get(key) for key in required):
        return None
    return {key: str(raw[key]) for key in required}


async def aggregate_product_counts_by_seller(
    seller_ids: list[str],
) -> dict[str, dict[str, int]]:
    if not seller_ids:
        return {}

    collection = get_catalog_products_collection()
    pipeline = [
        {"$match": {"seller_id": {"$in": seller_ids}}},
        {
            "$group": {
                "_id": "$seller_id",
                "total": {"$sum": 1},
                "published": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$eq": ["$is_available", True]},
                                    {"$ne": ["$view_only", True]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "view_only": {
                    "$sum": {"$cond": [{"$eq": ["$view_only", True]}, 1, 0]}
                },
                "unavailable": {
                    "$sum": {"$cond": [{"$eq": ["$is_available", False]}, 1, 0]}
                },
            }
        },
    ]
    rows = await collection.aggregate(pipeline).to_list(length=None)
    return {
        str(row["_id"]): {
            "total": int(row.get("total") or 0),
            "published": int(row.get("published") or 0),
            "view_only": int(row.get("view_only") or 0),
            "unavailable": int(row.get("unavailable") or 0),
        }
        for row in rows
    }


def build_marketplace_visibility_notes(
    doc: dict[str, Any],
    counts: dict[str, int] | None = None,
) -> list[str]:
    stats = counts or _EMPTY_COUNTS
    notes: list[str] = []

    status = doc.get("status")
    if status != "approved":
        if status == "expired":
            notes.append("Suscripción vencida: la tienda no aparece en marketplace ni home.")
        elif status == "pending":
            notes.append("Solicitud pendiente de aprobación.")
        elif status == "rejected":
            notes.append("Tienda rechazada.")
        return notes

    if not is_subscription_active(doc):
        notes.append("Suscripción inactiva o vencida.")

    if not doc.get("profile_photo_url"):
        notes.append("Falta foto de perfil.")
    if not doc.get("category_ids"):
        notes.append("Falta categoría de negocio en el perfil.")
    if doc.get("offers_delivery") is None:
        notes.append("No indicó si ofrece domicilio.")
    business = _parse_business_area(doc.get("business_area"))
    if business is None:
        notes.append("Falta municipio de la tienda en el perfil.")
    elif not is_profile_complete(doc):
        notes.append("Perfil público incompleto.")

    published = stats.get("published", 0)
    if stats.get("total", 0) == 0:
        notes.append("Sin productos en el catálogo.")
    elif published == 0:
        notes.append(
            "Tiene productos, pero ninguno publicado (deben estar disponibles y no ser solo vista)."
        )
    if stats.get("view_only", 0) > 0:
        notes.append(
            f"{stats['view_only']} producto(s) en modo solo vista (no aparecen en marketplace)."
        )
    if stats.get("unavailable", 0) > 0:
        notes.append(
            f"{stats['unavailable']} producto(s) marcados como no disponibles."
        )

    if business and published > 0 and is_subscription_active(doc) and is_profile_complete(doc):
        delivery_areas = doc.get("delivery_areas") or []
        delivery_names = [
            f"{area.get('municipality_name')} ({area.get('province_name')})"
            for area in delivery_areas
            if isinstance(area, dict) and area.get("municipality_name")
        ]
        location_hint = (
            f"Ubicación de la tienda: {business['municipality_name']} ({business['province_name']}). "
            "En marketplace/home solo los ven compradores en ese municipio"
        )
        if doc.get("offers_delivery") and delivery_names:
            location_hint += f", en municipios con domicilio ({', '.join(delivery_names[:3])}"
            if len(delivery_names) > 3:
                location_hint += f" y {len(delivery_names) - 3} más"
            location_hint += ")"
        elif doc.get("offers_delivery"):
            location_hint += " o con domicilio configurado a su municipio"
        else:
            location_hint += " (sin domicilio a otros municipios)"
        location_hint += ", o si el producto permite recogida en tienda."
        notes.append(location_hint)

    return notes
