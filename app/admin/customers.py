"""Listado de clientes del panel y el bloqueo de compras."""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from fastapi import HTTPException

from app.admin.schemas import AdminAppDownloadInfo, AdminCustomerPublic
from app.app_releases.service import map_user_app_downloads
from app.database import get_customers_collection, get_orders_collection


def _customer_id(customer_id: str) -> ObjectId:
    try:
        return ObjectId(customer_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.") from exc


def _phone(value: str) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) == 8:
        return f"+53{digits}"
    return str(value or "")


def _public(
    doc: dict,
    order_count: int,
    app_downloads: list[AdminAppDownloadInfo] | None = None,
) -> AdminCustomerPublic:
    created_at = doc.get("created_at")
    return AdminCustomerPublic(
        id=str(doc["_id"]),
        full_name=str(doc.get("full_name") or ""),
        email=str(doc.get("email") or ""),
        phone=_phone(doc.get("phone") or ""),
        identity_card=str(doc.get("identity_card") or ""),
        qvapay_username=str(doc.get("qvapay_username") or "").strip() or None,
        created_at=created_at if isinstance(created_at, datetime) else None,
        order_count=order_count,
        purchase_revoked=bool(doc.get("purchase_revoked")),
        app_downloads=list(app_downloads or []),
    )


async def _order_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    cursor = get_orders_collection().aggregate([
        {"$match": {"buyer_id": {"$type": "string", "$gt": ""}}},
        {"$group": {"_id": "$buyer_id", "order_count": {"$sum": 1}}},
    ])
    async for row in cursor:
        buyer_id = str(row.get("_id") or "")
        if buyer_id:
            counts[buyer_id] = int(row.get("order_count") or 0)
    return counts


async def list_admin_customers() -> list[AdminCustomerPublic]:
    counts = await _order_counts()
    docs = await get_customers_collection().find({}).to_list(length=None)
    docs.sort(key=lambda doc: doc.get("created_at") or datetime.min, reverse=True)
    customer_ids = [str(doc["_id"]) for doc in docs]
    downloads_by_user = await map_user_app_downloads(user_type="customer", user_ids=customer_ids)
    return [
        _public(
            doc,
            counts.get(str(doc["_id"]), 0),
            [
                AdminAppDownloadInfo(platform=item["platform"], version=item["version"])
                for item in downloads_by_user.get(str(doc["_id"]), [])
            ],
        )
        for doc in docs
    ]


async def set_customer_purchase_access(customer_id: str, *, purchase_revoked: bool) -> AdminCustomerPublic:
    oid = _customer_id(customer_id)
    result = await get_customers_collection().update_one(
        {"_id": oid},
        {"$set": {"purchase_revoked": purchase_revoked}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    doc = await get_customers_collection().find_one({"_id": oid})
    order_count = await get_orders_collection().count_documents({"buyer_id": str(oid)})
    downloads = await map_user_app_downloads(user_type="customer", user_ids=[str(oid)])
    return _public(
        doc,
        order_count,
        [
            AdminAppDownloadInfo(platform=item["platform"], version=item["version"])
            for item in downloads.get(str(oid), [])
        ],
    )
