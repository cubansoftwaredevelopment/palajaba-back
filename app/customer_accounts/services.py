from datetime import date, datetime, timedelta, timezone
import uuid
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, UploadFile

from app.auth.utils import create_customer_token, hash_password, verify_password
from app.config import settings
from app.database import (
    get_customer_contact_otp_challenges_collection,
    get_customer_otp_challenges_collection,
    get_customer_password_reset_challenges_collection,
    get_customers_collection,
    get_catalog_products_collection,
    get_orders_collection,
    get_registrations_collection,
)
from app.notifications.otp_manager import OTP_EXPIRES_IN_SECONDS, send_otp, verify_otp
from app.catalogs.media_storage import read_image_upload, remove_image, store_image
from app.utils.datetime import APP_DISPLAY_TZ, to_utc_naive, utc_now

from .schema import (
    CustomerAddressRequest,
    CustomerContactOtpConfirmRequest,
    CustomerContactOtpStartResponse,
    CustomerEmailUpdateRequest,
    CustomerIdentityCardUpdateRequest,
    CustomerLoginRequest,
    CustomerLoginResponse,
    CustomerOtpConfirmRequest,
    CustomerOtpResendRequest,
    CustomerOtpStartResponse,
    CustomerPasswordResetCompleteRequest,
    CustomerPasswordResetCompleteResponse,
    CustomerPasswordResetConfirmRequest,
    CustomerPasswordResetConfirmResponse,
    CustomerPasswordResetResendRequest,
    CustomerPasswordResetStartRequest,
    CustomerPasswordResetStartResponse,
    CustomerPhoneUpdateRequest,
    CustomerRegisterRequest,
)
from .utils import customer_public, mask_customer_phone, store_customer_order_location

STORE_TIMEZONE = APP_DISPLAY_TZ


async def ensure_customer_indexes() -> None:
    customers = get_customers_collection()
    await customers.create_index("email", unique=True)
    await customers.create_index("phone", unique=True)
    await customers.create_index("identity_card", unique=True)
    await get_customer_otp_challenges_collection().create_index("expires_at", expireAfterSeconds=0)
    contact_challenges = get_customer_contact_otp_challenges_collection()
    await contact_challenges.create_index("expires_at", expireAfterSeconds=0)
    await contact_challenges.create_index([("customer_id", 1), ("kind", 1)])
    reset_challenges = get_customer_password_reset_challenges_collection()
    await reset_challenges.create_index("expires_at", expireAfterSeconds=0)
    await reset_challenges.create_index("customer_id")


async def _get_registration_challenge(challenge_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(challenge_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a enviar tus datos.") from exc
    collection = get_customer_otp_challenges_collection()
    doc = await collection.find_one({"_id": oid})
    if not doc or to_utc_naive(doc["expires_at"]) <= to_utc_naive(utc_now()):
        if doc:
            await collection.delete_one({"_id": oid})
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a enviar tus datos.")
    return doc


async def start_customer_registration(payload: CustomerRegisterRequest) -> CustomerOtpStartResponse:
    customers = get_customers_collection()
    for field, value in (("email", payload.email), ("phone", payload.phone), ("identity_card", payload.identity_card)):
        if await customers.find_one({field: value}):
            labels = {"email": "correo", "phone": "teléfono", "identity_card": "carnet de identidad"}
            raise HTTPException(status_code=409, detail=f"Ya existe una cuenta con ese {labels[field]}.")

    email_result = await send_otp(email=payload.email)
    phone_result = await send_otp(phone_e164=f"+53{payload.phone}")
    now = to_utc_naive(utc_now())
    document = {
        "full_name": payload.full_name,
        "email": payload.email,
        "phone": payload.phone,
        "identity_card": payload.identity_card,
        "password_hash": hash_password(payload.password),
        "email_hash": email_result.hash,
        "phone_hash": phone_result.hash,
        "email_verified": False,
        "phone_verified": False,
        "email_expires_at": email_result.expires_at,
        "phone_expires_at": phone_result.expires_at,
        "created_at": now,
        "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS),
    }
    result = await get_customer_otp_challenges_collection().insert_one(document)
    return CustomerOtpStartResponse(
        challenge_id=str(result.inserted_id),
        email_expires_at=email_result.expires_at,
        phone_expires_at=phone_result.expires_at,
        message="Modo desarrollo: verificación OTP omitida." if settings.otp_verification_bypassed else "Te enviamos un código al correo y otro por SMS.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


async def resend_customer_registration(payload: CustomerOtpResendRequest) -> CustomerOtpStartResponse:
    doc = await _get_registration_challenge(payload.challenge_id)
    if payload.channel == "email":
        sent = await send_otp(email=doc["email"])
        updates = {"email_hash": sent.hash, "email_verified": False, "email_expires_at": sent.expires_at}
        email_expiry, phone_expiry = sent.expires_at, doc.get("phone_expires_at")
    else:
        sent = await send_otp(phone_e164=f"+53{doc['phone']}")
        updates = {"phone_hash": sent.hash, "phone_verified": False, "phone_expires_at": sent.expires_at}
        email_expiry, phone_expiry = doc.get("email_expires_at"), sent.expires_at
    await get_customer_otp_challenges_collection().update_one({"_id": doc["_id"]}, {"$set": updates})
    return CustomerOtpStartResponse(
        challenge_id=payload.challenge_id,
        email_expires_at=email_expiry,
        phone_expires_at=phone_expiry,
        message="Código reenviado.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


async def confirm_customer_registration(payload: CustomerOtpConfirmRequest) -> CustomerLoginResponse:
    doc = await _get_registration_challenge(payload.challenge_id)
    challenges = get_customer_otp_challenges_collection()
    if not doc.get("email_verified"):
        await verify_otp(otp_hash=doc["email_hash"], code=payload.email_code)
        await challenges.update_one({"_id": doc["_id"]}, {"$set": {"email_verified": True}})
    if not doc.get("phone_verified"):
        await verify_otp(otp_hash=doc["phone_hash"], code=payload.phone_code)
        await challenges.update_one({"_id": doc["_id"]}, {"$set": {"phone_verified": True}})
    customer = {
        "full_name": doc["full_name"],
        "email": doc["email"],
        "phone": doc["phone"],
        "identity_card": doc["identity_card"],
        "password_hash": doc["password_hash"],
        "profile_photo_url": None,
        "addresses": [],
        "favorite_product_ids": [],
        "favorites": [],
        "created_at": to_utc_naive(utc_now()),
    }
    try:
        result = await get_customers_collection().insert_one(customer)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="El correo, teléfono o carnet ya pertenece a una cuenta.") from exc
    customer["_id"] = result.inserted_id
    await challenges.delete_one({"_id": doc["_id"]})
    return CustomerLoginResponse(
        access_token=create_customer_token(customer_id=str(result.inserted_id), full_name=customer["full_name"]),
        customer=customer_public(customer),
    )


async def customer_login(payload: CustomerLoginRequest) -> CustomerLoginResponse:
    customer = await get_customers_collection().find_one({"phone": payload.phone})
    if not customer or not verify_password(payload.password, customer["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.")
    return CustomerLoginResponse(
        access_token=create_customer_token(customer_id=str(customer["_id"]), full_name=customer["full_name"]),
        customer=customer_public(customer),
    )


async def get_customer(customer_id: str):
    doc = await get_customers_collection().find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    return customer_public(doc)


async def update_customer(customer_id: str, payload: dict[str, Any]):
    full_name = " ".join(str(payload.get("full_name") or "").split())
    if len(full_name) < 2 or len(full_name) > 120:
        raise HTTPException(status_code=422, detail="El nombre debe tener entre 2 y 120 caracteres.")
    await get_customers_collection().update_one({"_id": ObjectId(customer_id)}, {"$set": {"full_name": full_name}})
    return await get_customer(customer_id)


async def start_customer_contact_change(*, customer_id: str, kind: str, value: str) -> CustomerContactOtpStartResponse:
    customer_oid = ObjectId(customer_id)
    customers = get_customers_collection()
    customer = await customers.find_one({"_id": customer_oid})
    if not customer:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    if value == customer.get(kind):
        label = "correo" if kind == "email" else "teléfono"
        raise HTTPException(status_code=400, detail=f"Ese ya es tu {label}.")
    if await customers.find_one({kind: value, "_id": {"$ne": customer_oid}}):
        label = "correo" if kind == "email" else "teléfono"
        raise HTTPException(status_code=409, detail=f"Ese {label} ya está asociado a otra cuenta.")
    sent = await send_otp(email=value) if kind == "email" else await send_otp(phone_e164=f"+53{value}")
    collection = get_customer_contact_otp_challenges_collection()
    await collection.delete_many({"customer_id": customer_id, "kind": kind})
    now = to_utc_naive(utc_now())
    result = await collection.insert_one({
        "customer_id": customer_id,
        "kind": kind,
        kind: value,
        "otp_hash": sent.hash,
        "created_at": now,
        "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS),
    })
    target = "nuevo correo" if kind == "email" else "nuevo número de teléfono"
    return CustomerContactOtpStartResponse(
        challenge_id=str(result.inserted_id),
        expires_at=sent.expires_at,
        message="Modo desarrollo: verificación OTP omitida." if settings.otp_verification_bypassed else f"Te enviamos un código al {target}.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


async def confirm_customer_contact_change(payload: CustomerContactOtpConfirmRequest, customer_id: str):
    try:
        challenge_oid = ObjectId(payload.challenge_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a pedir el código.") from exc
    challenges = get_customer_contact_otp_challenges_collection()
    doc = await challenges.find_one({"_id": challenge_oid, "customer_id": customer_id})
    if not doc or to_utc_naive(doc["expires_at"]) <= to_utc_naive(utc_now()):
        if doc:
            await challenges.delete_one({"_id": challenge_oid})
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a pedir el código.")
    await verify_otp(otp_hash=doc.get("otp_hash") or "", code=payload.code)
    try:
        result = await get_customers_collection().update_one(
            {"_id": ObjectId(customer_id)}, {"$set": {doc["kind"]: doc[doc["kind"]]}}
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Ese correo o teléfono ya está asociado a otra cuenta.") from exc
    if not result.matched_count:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    await challenges.delete_one({"_id": challenge_oid})
    return await get_customer(customer_id)


async def update_customer_identity_card(payload: CustomerIdentityCardUpdateRequest, customer_id: str):
    customer_oid = ObjectId(customer_id)
    customers = get_customers_collection()
    if await customers.find_one({"identity_card": payload.identity_card, "_id": {"$ne": customer_oid}}):
        raise HTTPException(status_code=409, detail="Ese carnet ya está asociado a otra cuenta.")
    try:
        await customers.update_one({"_id": customer_oid}, {"$set": {"identity_card": payload.identity_card}})
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Ese carnet ya está asociado a otra cuenta.") from exc
    return await get_customer(customer_id)


async def _get_password_reset_challenge(challenge_id: str) -> dict[str, Any]:
    try:
        challenge_oid = ObjectId(challenge_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="La verificación expiró. Solicita un código nuevo.") from exc
    collection = get_customer_password_reset_challenges_collection()
    doc = await collection.find_one({"_id": challenge_oid})
    if not doc or to_utc_naive(doc["expires_at"]) <= to_utc_naive(utc_now()):
        if doc:
            await collection.delete_one({"_id": challenge_oid})
        raise HTTPException(status_code=404, detail="La verificación expiró. Solicita un código nuevo.")
    return doc


async def start_customer_password_reset(payload: CustomerPasswordResetStartRequest) -> CustomerPasswordResetStartResponse:
    customer = await get_customers_collection().find_one({"phone": payload.phone})
    if not customer:
        raise HTTPException(status_code=404, detail="No encontramos una cuenta con ese teléfono.")
    sent = await send_otp(phone_e164=f"+53{payload.phone}")
    collection = get_customer_password_reset_challenges_collection()
    customer_id = str(customer["_id"])
    await collection.delete_many({"customer_id": customer_id})
    now = to_utc_naive(utc_now())
    result = await collection.insert_one({
        "customer_id": customer_id,
        "phone": payload.phone,
        "otp_hash": sent.hash,
        "verified": False,
        "created_at": now,
        "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS),
    })
    return CustomerPasswordResetStartResponse(
        challenge_id=str(result.inserted_id),
        phone_hint=mask_customer_phone(payload.phone),
        expires_at=sent.expires_at,
        message="Modo desarrollo: verificación OTP omitida." if settings.otp_verification_bypassed else "Te enviamos un código por SMS al teléfono de tu cuenta.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


async def resend_customer_password_reset(payload: CustomerPasswordResetResendRequest) -> CustomerPasswordResetStartResponse:
    doc = await _get_password_reset_challenge(payload.challenge_id)
    sent = await send_otp(phone_e164=f"+53{doc['phone']}")
    now = to_utc_naive(utc_now())
    await get_customer_password_reset_challenges_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": {"otp_hash": sent.hash, "verified": False, "created_at": now, "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS)}},
    )
    return CustomerPasswordResetStartResponse(
        challenge_id=payload.challenge_id,
        phone_hint=mask_customer_phone(doc["phone"]),
        expires_at=sent.expires_at,
        message="Te enviamos un nuevo código por SMS.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


async def confirm_customer_password_reset(payload: CustomerPasswordResetConfirmRequest) -> CustomerPasswordResetConfirmResponse:
    doc = await _get_password_reset_challenge(payload.challenge_id)
    await verify_otp(otp_hash=doc.get("otp_hash") or "", code=payload.code)
    await get_customer_password_reset_challenges_collection().update_one({"_id": doc["_id"]}, {"$set": {"verified": True}})
    return CustomerPasswordResetConfirmResponse(
        challenge_id=payload.challenge_id,
        message="Identidad confirmada. Elige una nueva contraseña.",
    )


async def complete_customer_password_reset(payload: CustomerPasswordResetCompleteRequest) -> CustomerPasswordResetCompleteResponse:
    doc = await _get_password_reset_challenge(payload.challenge_id)
    if not doc.get("verified"):
        raise HTTPException(status_code=400, detail="Primero confirma el código SMS.")
    try:
        customer_oid = ObjectId(doc["customer_id"])
    except Exception as exc:
        raise HTTPException(status_code=404, detail="No encontramos una cuenta con ese teléfono.") from exc
    result = await get_customers_collection().update_one(
        {"_id": customer_oid},
        {"$set": {"password_hash": hash_password(payload.password), "updated_at": to_utc_naive(utc_now())}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="No encontramos una cuenta con ese teléfono.")
    await get_customer_password_reset_challenges_collection().delete_one({"_id": doc["_id"]})
    return CustomerPasswordResetCompleteResponse(message="Contraseña actualizada. Ya puedes iniciar sesión.")


async def upload_customer_photo(photo: UploadFile, customer_id: str):
    collection = get_customers_collection()
    doc = await collection.find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    content, content_type = await read_image_upload(photo)
    image = await store_image(content, content_type, scope="profiles", owner_id=customer_id)
    await collection.update_one({"_id": doc["_id"]}, {"$set": {"profile_photo_url": image.url}})
    if doc.get("profile_photo_url"):
        await remove_image(doc["profile_photo_url"])
    return await get_customer(customer_id)


async def add_customer_address(payload: CustomerAddressRequest, customer_id: str):
    address = {"id": str(uuid.uuid4()), **payload.model_dump()}
    await get_customers_collection().update_one({"_id": ObjectId(customer_id)}, {"$push": {"addresses": address}})
    return await get_customer(customer_id)


async def update_customer_address(address_id: str, payload: CustomerAddressRequest, customer_id: str):
    result = await get_customers_collection().update_one(
        {"_id": ObjectId(customer_id), "addresses.id": address_id},
        {"$set": {f"addresses.$.{field}": value for field, value in payload.model_dump().items()}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="No encontramos esa dirección guardada.")
    return await get_customer(customer_id)


async def delete_customer_address(address_id: str, customer_id: str):
    await get_customers_collection().update_one(
        {"_id": ObjectId(customer_id)}, {"$pull": {"addresses": {"id": address_id}}}
    )
    return await get_customer(customer_id)


async def add_customer_favorite(product_id: str, customer_id: str):
    try:
        product_oid = ObjectId(product_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Producto no encontrado.") from exc
    product = await get_catalog_products_collection().find_one({"_id": product_oid})
    if product is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    seller = None
    try:
        seller = await get_registrations_collection().find_one({"_id": ObjectId(str(product.get("seller_id")))} )
    except Exception:
        pass
    snapshot = {
        "id": str(product_oid),
        "name": product.get("name") or "Producto",
        "image_url": product.get("image_url") or "",
        "base_price": float(product.get("base_price") or 0),
        "base_currency": product.get("base_currency") or "CUP",
        "store": {
            "store_name": (seller or {}).get("store_name") or "Tienda",
            "store_slug": (seller or {}).get("store_slug") or "",
        },
    }
    await get_customers_collection().update_one(
        {"_id": ObjectId(customer_id)},
        {"$addToSet": {"favorite_product_ids": product_id, "favorites": snapshot}},
    )
    return await get_customer(customer_id)


async def remove_customer_favorite(product_id: str, customer_id: str):
    await get_customers_collection().update_one(
        {"_id": ObjectId(customer_id)},
        {"$pull": {"favorite_product_ids": product_id, "favorites": {"id": product_id}}},
    )
    return await get_customer(customer_id)


async def list_customer_orders(customer_id: str):
    docs = await get_orders_collection().find({"buyer_id": customer_id}).sort("created_at", -1).to_list(length=None)
    product_ids = set()
    for doc in docs:
        for item in doc.get("items") or []:
            try:
                product_ids.add(ObjectId(str(item.get("product_id") or "")))
            except Exception:
                continue
    products_by_id = {}
    if product_ids:
        products = await get_catalog_products_collection().find(
            {"_id": {"$in": list(product_ids)}}, {"image_url": 1, "images": 1}
        ).to_list(length=len(product_ids))
        products_by_id = {str(product["_id"]): product for product in products}

    def items_with_images(doc):
        items = []
        for item in doc.get("items") or []:
            item_data = dict(item)
            product = products_by_id.get(str(item_data.get("product_id") or ""), {})
            images = product.get("images") or []
            primary = next((image for image in images if isinstance(image, dict) and image.get("is_frontal") and image.get("image_url")), None)
            any_image = next((image for image in images if isinstance(image, dict) and image.get("image_url")), None)
            item_data["image_url"] = (primary or any_image or {}).get("image_url") or product.get("image_url") or ""
            items.append(item_data)
        return items

    return [
        {
            "id": str(doc["_id"]), "store_id": doc["seller_id"], "store_name": doc["store_name"],
            "status": doc["status"], "items": items_with_images(doc), "subtotals": doc.get("subtotals") or [],
            "delivery_requested": bool(doc.get("delivery_requested")), "delivery_price": doc.get("delivery_price"),
            "delivery_currency": doc.get("delivery_currency"), "created_at": doc["created_at"],
            "updated_at": doc["updated_at"], "completed_at": doc.get("completed_at"),
            "payment_method": doc.get("payment_method") or "contact",
            "qvapay": _customer_order_qvapay_public(doc.get("qvapay")),
            "store_agreements": doc.get("store_agreements") if isinstance(doc.get("store_agreements"), dict) else None,
        }
        for doc in docs
    ]


def _customer_order_qvapay_public(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "request_status": value.get("request_status"),
        "payment_status": value.get("payment_status"),
        "invoice_url": value.get("invoice_url"),
        "invoice_amount_usd": value.get("invoice_amount_usd"),
        "products_amount_usd": value.get("products_amount_usd"),
        "delivery_amount_usd": value.get("delivery_amount_usd"),
        "fee_usd": value.get("fee_usd"),
        "evidence": value.get("evidence"),
        "evidence_history": value.get("evidence_history") if isinstance(value.get("evidence_history"), list) else [],
        "buyer_support_reported": bool(value.get("buyer_support_reported")),
        "seller_support_reported": bool(value.get("seller_support_reported")),
        "release_status": value.get("release_status"),
    }


async def list_store_customers(
    seller_id: str,
    *,
    offset: int = 0,
    limit: int = 20,
    orders_limit: int = 10,
    customer_id: str | None = None,
    orders_offset: int = 0,
    search: str = "",
    location: str = "",
    currency: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    products: list[str] | None = None,
):
    orders = await get_orders_collection().find(
        {"seller_id": seller_id, "buyer_id": {"$exists": True}}
    ).sort([("created_at", -1), ("_id", -1)]).to_list(length=None)
    summaries: dict[str, dict[str, Any]] = {}
    for order in orders:
        buyer_id = str(order.get("buyer_id") or "")
        if not buyer_id:
            continue
        summary = summaries.setdefault(buyer_id, {
            "id": buyer_id,
            "full_name": order.get("buyer_name") or "Cliente",
            "email": order.get("buyer_email") or "",
            "phone": order.get("buyer_phone") or "",
            "orders_count": 0,
            "last_order_at": order.get("created_at"),
            "orders": [],
        })
        summary["orders_count"] += 1
        summary["orders"].append({
            "id": str(order["_id"]),
            "status": order["status"],
            "created_at": order["created_at"],
            "subtotals": order.get("subtotals") or [],
            "payment_currency": order.get("payment_currency"),
            "buyer_zone": order.get("buyer_zone"),
            "products": [item.get("name") for item in order.get("items") or [] if item.get("name")],
        })

    all_customers = list(summaries.values())
    product_options = sorted({product for customer in all_customers for order in customer["orders"] for product in order["products"]}, key=str.casefold)
    currency_options = sorted({
        code for customer in all_customers for order in customer["orders"]
        for code in ([order.get("payment_currency")] + [item.get("currency") for item in order["subtotals"]]) if code
    })
    location_options = {}
    for customer in all_customers:
        for order in customer["orders"]:
            zone = order.get("buyer_zone") or {}
            province = str(zone.get("province_name") or "").strip()
            municipality = str(zone.get("municipality_name") or "").strip()
            if province or municipality:
                key = f"{zone.get('province_id') or province}|{zone.get('municipality_id') or municipality}"
                location_options[key] = ", ".join(part for part in (municipality, province) if part)

    selected_products = {value.strip().casefold() for value in (products or []) if value.strip()}
    query_text = search.strip().casefold()
    filtered_customers = []
    for customer in all_customers:
        matching_orders = customer["orders"]
        if date_from or date_to:
            def order_is_in_date_range(order):
                created_at = order.get("created_at")
                if isinstance(created_at, datetime):
                    aware_created_at = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
                    order_date = aware_created_at.astimezone(STORE_TIMEZONE).date()
                elif isinstance(created_at, date):
                    order_date = created_at
                else:
                    try:
                        order_date = date.fromisoformat(str(created_at)[:10])
                    except (TypeError, ValueError):
                        return False
                return (date_from is None or order_date >= date_from) and (date_to is None or order_date <= date_to)

            matching_orders = [order for order in matching_orders if order_is_in_date_range(order)]
        if selected_products:
            matching_orders = [order for order in matching_orders if selected_products.intersection(product.casefold() for product in order["products"])]
        if location:
            matching_orders = [order for order in matching_orders if store_customer_order_location(order) == location]
        if currency:
            matching_orders = [order for order in matching_orders if currency == (order.get("payment_currency") or "") or any(item.get("currency") == currency for item in order["subtotals"])]
        if query_text:
            searchable = " ".join([
                customer["full_name"], customer["email"], customer["phone"],
                *[str(order["id"])[-6:] for order in matching_orders],
                *[product for order in matching_orders for product in order["products"]],
            ]).casefold()
            if query_text not in searchable:
                continue
        if not matching_orders:
            continue
        customer_copy = {**customer, "orders": matching_orders}
        if customer_id and customer["id"] == customer_id:
            customer_copy["orders"] = matching_orders[orders_offset:orders_offset + orders_limit]
            customer_copy["orders_offset"] = orders_offset
            customer_copy["orders_has_more"] = orders_offset + len(customer_copy["orders"]) < len(matching_orders)
            return {"customer": customer_copy}
        filtered_customers.append(customer_copy)

    total = len(filtered_customers)
    page = filtered_customers[offset:offset + limit]
    for customer in page:
        all_orders = customer["orders"]
        customer["orders"] = all_orders[:orders_limit]
        customer["orders_offset"] = 0
        customer["orders_has_more"] = len(all_orders) > orders_limit
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
        "product_options": product_options,
        "currency_options": currency_options,
        "location_options": [
            {"value": key, "label": value}
            for key, value in sorted(location_options.items(), key=lambda item: item[1].casefold())
        ],
    }
