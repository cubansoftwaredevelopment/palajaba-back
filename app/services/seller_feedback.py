from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING

from app.database import get_registrations_collection, get_seller_feedback_collection
from app.schemas.seller_feedback import (
    AdminFeedbackDeleteResult,
    AdminFeedbackPublic,
    AdminFeedbackUnreadCount,
    SellerFeedbackCreate,
    SellerFeedbackSubmitResult,
)
from app.utils.datetime import to_utc_naive, utc_now
from app.utils.store_slug import store_name_to_slug

FeedbackFilter = Literal["all", "unread", "complaint", "suggestion"]


async def ensure_seller_feedback_indexes() -> None:
    collection = get_seller_feedback_collection()
    await collection.create_index([("created_at", DESCENDING)])
    await collection.create_index([("read_at", ASCENDING), ("created_at", DESCENDING)])
    await collection.create_index([("seller_id", ASCENDING), ("created_at", DESCENDING)])
    await collection.create_index([("feedback_type", ASCENDING), ("created_at", DESCENDING)])


def _document_to_public(doc: dict[str, Any]) -> AdminFeedbackPublic:
    return AdminFeedbackPublic(
        id=str(doc["_id"]),
        seller_id=str(doc["seller_id"]),
        store_name=doc["store_name"],
        store_slug=doc.get("store_slug"),
        feedback_type=doc["feedback_type"],
        message=doc["message"],
        read_at=doc.get("read_at"),
        created_at=doc["created_at"],
    )


async def _get_seller_doc(seller_id: str) -> dict[str, Any]:
    try:
        seller_oid = ObjectId(seller_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        ) from exc

    seller = await get_registrations_collection().find_one({"_id": seller_oid})
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendedor no encontrado.",
        )
    return seller


async def _get_feedback_doc(feedback_id: str) -> dict[str, Any]:
    try:
        feedback_oid = ObjectId(feedback_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensaje no encontrado.",
        ) from exc

    doc = await get_seller_feedback_collection().find_one({"_id": feedback_oid})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensaje no encontrado.",
        )
    return doc


def _build_admin_list_query(
    *,
    feedback_filter: FeedbackFilter,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if feedback_filter == "unread":
        query["read_at"] = None
    elif feedback_filter == "complaint":
        query["feedback_type"] = "complaint"
    elif feedback_filter == "suggestion":
        query["feedback_type"] = "suggestion"
    return query


async def submit_seller_feedback(
    seller_id: str,
    payload: SellerFeedbackCreate,
) -> SellerFeedbackSubmitResult:
    seller = await _get_seller_doc(seller_id)
    now = to_utc_naive(utc_now())
    doc = {
        "seller_id": seller["_id"],
        "store_name": seller["store_name"],
        "store_slug": seller.get("store_slug") or store_name_to_slug(seller["store_name"]),
        "feedback_type": payload.feedback_type,
        "message": payload.message,
        "read_at": None,
        "created_at": now,
    }
    result = await get_seller_feedback_collection().insert_one(doc)
    return SellerFeedbackSubmitResult(
        id=str(result.inserted_id),
        message="Gracias. Recibimos tu mensaje y lo revisará el equipo de Pa' La Jaba.",
    )


async def list_admin_feedback(
    *,
    feedback_filter: FeedbackFilter = "all",
) -> list[AdminFeedbackPublic]:
    query = _build_admin_list_query(feedback_filter=feedback_filter)
    docs = (
        await get_seller_feedback_collection()
        .find(query)
        .sort("created_at", DESCENDING)
        .to_list(length=500)
    )
    return [_document_to_public(doc) for doc in docs]


async def get_admin_feedback_unread_count() -> AdminFeedbackUnreadCount:
    count = await get_seller_feedback_collection().count_documents({"read_at": None})
    return AdminFeedbackUnreadCount(unread_count=count)


async def mark_admin_feedback_read(feedback_id: str) -> AdminFeedbackPublic:
    doc = await _get_feedback_doc(feedback_id)
    if doc.get("read_at") is not None:
        return _document_to_public(doc)

    now = to_utc_naive(utc_now())
    await get_seller_feedback_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": {"read_at": now}},
    )
    updated = {**doc, "read_at": now}
    return _document_to_public(updated)


async def delete_admin_feedback(feedback_id: str) -> AdminFeedbackDeleteResult:
    doc = await _get_feedback_doc(feedback_id)
    await get_seller_feedback_collection().delete_one({"_id": doc["_id"]})
    return AdminFeedbackDeleteResult(
        id=str(doc["_id"]),
        message="Mensaje eliminado.",
    )
