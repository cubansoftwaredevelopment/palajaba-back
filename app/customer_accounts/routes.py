from datetime import timedelta
import uuid
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.auth.utils import create_customer_token, hash_password, require_customer, require_seller, verify_password
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
from app.services.media_storage import read_image_upload, remove_image, store_image
from app.utils.datetime import to_utc_naive, utc_now

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if digits.startswith("53") and len(digits) == 10:
        digits = digits[2:]
    if len(digits) != 8:
        raise ValueError("El teléfono debe tener 8 dígitos.")
    return digits


class CustomerRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=254)
    phone: str
    identity_card: str
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("Ingresa un correo válido.")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone_field(cls, value: str) -> str:
        return _normalize_phone(value)

    @field_validator("identity_card")
    @classmethod
    def validate_identity_card(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El carnet de identidad es obligatorio.")
        return value


class CustomerOtpStartResponse(BaseModel):
    challenge_id: str
    email_expires_at: str | None = None
    phone_expires_at: str | None = None
    message: str
    otp_bypassed: bool = False


class CustomerOtpResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    channel: str = Field(..., pattern="^(email|phone)$")


class CustomerOtpConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    email_code: str = Field(..., min_length=4, max_length=8)
    phone_code: str = Field(..., min_length=4, max_length=8)


class CustomerLoginRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("phone")
    @classmethod
    def normalize_login_phone(cls, value: str) -> str:
        return _normalize_phone(value)


class CustomerPublic(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str
    identity_card: str
    profile_photo_url: str | None = None
    addresses: list[dict[str, Any]] = Field(default_factory=list)
    favorite_product_ids: list[str] = Field(default_factory=list)
    favorites: list[dict[str, Any]] = Field(default_factory=list)


class CustomerLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer: CustomerPublic


class CustomerAddressRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=48)
    address: str = Field(..., min_length=3, max_length=300)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    @model_validator(mode="after")
    def validate_pin_pair(self):
        return self


class CustomerEmailUpdateRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("Ingresa un correo válido.")
        return normalized


class CustomerPhoneUpdateRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def normalize_phone_field(cls, value: str) -> str:
        return _normalize_phone(value)


class CustomerContactOtpStartResponse(BaseModel):
    challenge_id: str
    expires_at: str | None = None
    message: str
    otp_bypassed: bool = False


class CustomerContactOtpConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    code: str = Field(..., min_length=4, max_length=8)


class CustomerIdentityCardUpdateRequest(BaseModel):
    identity_card: str = Field(..., min_length=1, max_length=64)

    @field_validator("identity_card")
    @classmethod
    def normalize_identity_card(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El carnet de identidad es obligatorio.")
        return value


class CustomerPasswordResetStartRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def normalize_phone_field(cls, value: str) -> str:
        return _normalize_phone(value)


class CustomerPasswordResetStartResponse(BaseModel):
    challenge_id: str
    phone_hint: str
    expires_at: str | None = None
    message: str
    otp_bypassed: bool = False


class CustomerPasswordResetResendRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)


class CustomerPasswordResetConfirmRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    code: str = Field(..., min_length=4, max_length=8)


class CustomerPasswordResetCompleteRequest(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=6, max_length=128)


class CustomerPasswordResetConfirmResponse(BaseModel):
    challenge_id: str
    message: str


class CustomerPasswordResetCompleteResponse(BaseModel):
    message: str


def _public(doc: dict[str, Any]) -> CustomerPublic:
    return CustomerPublic(
        id=str(doc["_id"]),
        full_name=doc["full_name"],
        email=doc["email"],
        phone=f"+53{doc['phone']}",
        identity_card=doc["identity_card"],
        profile_photo_url=doc.get("profile_photo_url"),
        addresses=doc.get("addresses") or [],
        favorite_product_ids=doc.get("favorite_product_ids") or [],
        favorites=doc.get("favorites") or [],
    )


async def ensure_customer_indexes() -> None:
    customers = get_customers_collection()
    await customers.create_index("email", unique=True)
    await customers.create_index("phone", unique=True)
    await customers.create_index("identity_card", unique=True)
    challenges = get_customer_otp_challenges_collection()
    await challenges.create_index("expires_at", expireAfterSeconds=0)
    contact_challenges = get_customer_contact_otp_challenges_collection()
    await contact_challenges.create_index("expires_at", expireAfterSeconds=0)
    await contact_challenges.create_index([("customer_id", 1), ("kind", 1)])
    reset_challenges = get_customer_password_reset_challenges_collection()
    await reset_challenges.create_index("expires_at", expireAfterSeconds=0)
    await reset_challenges.create_index("customer_id")


async def _get_challenge(challenge_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(challenge_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a enviar tus datos.") from exc
    doc = await get_customer_otp_challenges_collection().find_one({"_id": oid})
    if not doc or to_utc_naive(doc["expires_at"]) <= to_utc_naive(utc_now()):
        if doc:
            await get_customer_otp_challenges_collection().delete_one({"_id": oid})
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a enviar tus datos.")
    return doc


@router.post("/register/otp/start", response_model=CustomerOtpStartResponse)
async def start_customer_registration(payload: CustomerRegisterRequest):
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


@router.post("/register/otp/resend", response_model=CustomerOtpStartResponse)
async def resend_customer_registration(payload: CustomerOtpResendRequest):
    doc = await _get_challenge(payload.challenge_id)
    updates: dict[str, Any]
    if payload.channel == "email":
        sent = await send_otp(email=doc["email"])
        updates = {"email_hash": sent.hash, "email_verified": False, "email_expires_at": sent.expires_at}
        email_expiry = sent.expires_at
        phone_expiry = doc.get("phone_expires_at")
    else:
        sent = await send_otp(phone_e164=f"+53{doc['phone']}")
        updates = {"phone_hash": sent.hash, "phone_verified": False, "phone_expires_at": sent.expires_at}
        email_expiry = doc.get("email_expires_at")
        phone_expiry = sent.expires_at
    await get_customer_otp_challenges_collection().update_one({"_id": doc["_id"]}, {"$set": updates})
    return CustomerOtpStartResponse(
        challenge_id=payload.challenge_id,
        email_expires_at=email_expiry,
        phone_expires_at=phone_expiry,
        message="Código reenviado.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


@router.post("/register/otp/confirm", response_model=CustomerLoginResponse, status_code=201)
async def confirm_customer_registration(payload: CustomerOtpConfirmRequest):
    doc = await _get_challenge(payload.challenge_id)
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
        customer=_public(customer),
    )


@router.post("/login", response_model=CustomerLoginResponse)
async def customer_login(payload: CustomerLoginRequest):
    customer = await get_customers_collection().find_one({"phone": payload.phone})
    if not customer or not verify_password(payload.password, customer["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.")
    return CustomerLoginResponse(
        access_token=create_customer_token(customer_id=str(customer["_id"]), full_name=customer["full_name"]),
        customer=_public(customer),
    )


@router.get("/me", response_model=CustomerPublic)
async def get_my_customer(customer_payload: dict = Depends(require_customer)):
    doc = await get_customers_collection().find_one({"_id": ObjectId(customer_payload["customer_id"])})
    if not doc:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    return _public(doc)


@router.patch("/me", response_model=CustomerPublic)
async def update_my_customer(payload: dict[str, Any], customer_payload: dict = Depends(require_customer)):
    full_name = " ".join(str(payload.get("full_name") or "").split())
    if len(full_name) < 2 or len(full_name) > 120:
        raise HTTPException(status_code=422, detail="El nombre debe tener entre 2 y 120 caracteres.")
    collection = get_customers_collection()
    await collection.update_one({"_id": ObjectId(customer_payload["customer_id"])}, {"$set": {"full_name": full_name}})
    return await get_my_customer(customer_payload)


async def _start_customer_contact_change(*, customer_id: str, kind: str, value: str):
    customer_oid = ObjectId(customer_id)
    customer = await get_customers_collection().find_one({"_id": customer_oid})
    if not customer:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    if value == customer.get(kind):
        label = "correo" if kind == "email" else "teléfono"
        raise HTTPException(status_code=400, detail=f"Ese ya es tu {label}.")
    if await get_customers_collection().find_one({kind: value, "_id": {"$ne": customer_oid}}):
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
        message=(
            "Modo desarrollo: verificación OTP omitida."
            if settings.otp_verification_bypassed
            else f"Te enviamos un código al {target}."
        ),
        otp_bypassed=settings.otp_verification_bypassed,
    )


@router.post("/me/email/otp/start", response_model=CustomerContactOtpStartResponse)
async def start_customer_email_change(payload: CustomerEmailUpdateRequest, customer_payload: dict = Depends(require_customer)):
    return await _start_customer_contact_change(
        customer_id=customer_payload["customer_id"], kind="email", value=payload.email,
    )


@router.post("/me/phone/otp/start", response_model=CustomerContactOtpStartResponse)
async def start_customer_phone_change(payload: CustomerPhoneUpdateRequest, customer_payload: dict = Depends(require_customer)):
    return await _start_customer_contact_change(
        customer_id=customer_payload["customer_id"], kind="phone", value=payload.phone,
    )


@router.post("/me/contact-otp/confirm", response_model=CustomerPublic)
async def confirm_customer_contact_change(
    payload: CustomerContactOtpConfirmRequest,
    customer_payload: dict = Depends(require_customer),
):
    try:
        challenge_oid = ObjectId(payload.challenge_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a pedir el código.") from exc
    challenges = get_customer_contact_otp_challenges_collection()
    doc = await challenges.find_one({"_id": challenge_oid, "customer_id": customer_payload["customer_id"]})
    if not doc or to_utc_naive(doc["expires_at"]) <= to_utc_naive(utc_now()):
        if doc:
            await challenges.delete_one({"_id": challenge_oid})
        raise HTTPException(status_code=404, detail="La verificación expiró. Vuelve a pedir el código.")
    await verify_otp(otp_hash=doc.get("otp_hash") or "", code=payload.code)
    try:
        result = await get_customers_collection().update_one(
            {"_id": ObjectId(customer_payload["customer_id"])},
            {"$set": {doc["kind"]: doc[doc["kind"]]}},
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Ese correo o teléfono ya está asociado a otra cuenta.") from exc
    if not result.matched_count:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    await challenges.delete_one({"_id": challenge_oid})
    return await get_my_customer(customer_payload)


@router.patch("/me/identity-card", response_model=CustomerPublic)
async def update_customer_identity_card(
    payload: CustomerIdentityCardUpdateRequest,
    customer_payload: dict = Depends(require_customer),
):
    customer_oid = ObjectId(customer_payload["customer_id"])
    if await get_customers_collection().find_one({"identity_card": payload.identity_card, "_id": {"$ne": customer_oid}}):
        raise HTTPException(status_code=409, detail="Ese carnet ya está asociado a otra cuenta.")
    try:
        await get_customers_collection().update_one(
            {"_id": customer_oid}, {"$set": {"identity_card": payload.identity_card}},
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Ese carnet ya está asociado a otra cuenta.") from exc
    return await get_my_customer(customer_payload)


def _mask_customer_phone(phone: str) -> str:
    digits = "".join(character for character in str(phone or "") if character.isdigit())[-8:]
    return f"{digits[:2]}****{digits[-2:]}" if len(digits) == 8 else "***"


async def _get_customer_password_reset_challenge(challenge_id: str) -> dict[str, Any]:
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


@router.post("/password-reset/start", response_model=CustomerPasswordResetStartResponse)
async def start_customer_password_reset(payload: CustomerPasswordResetStartRequest):
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
        phone_hint=_mask_customer_phone(payload.phone),
        expires_at=sent.expires_at,
        message="Modo desarrollo: verificación OTP omitida." if settings.otp_verification_bypassed else "Te enviamos un código por SMS al teléfono de tu cuenta.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


@router.post("/password-reset/otp/resend", response_model=CustomerPasswordResetStartResponse)
async def resend_customer_password_reset(payload: CustomerPasswordResetResendRequest):
    doc = await _get_customer_password_reset_challenge(payload.challenge_id)
    sent = await send_otp(phone_e164=f"+53{doc['phone']}")
    now = to_utc_naive(utc_now())
    await get_customer_password_reset_challenges_collection().update_one(
        {"_id": doc["_id"]},
        {"$set": {"otp_hash": sent.hash, "verified": False, "created_at": now, "expires_at": now + timedelta(seconds=OTP_EXPIRES_IN_SECONDS)}},
    )
    return CustomerPasswordResetStartResponse(
        challenge_id=payload.challenge_id,
        phone_hint=_mask_customer_phone(doc["phone"]),
        expires_at=sent.expires_at,
        message="Te enviamos un nuevo código por SMS.",
        otp_bypassed=settings.otp_verification_bypassed,
    )


@router.post("/password-reset/otp/confirm", response_model=CustomerPasswordResetConfirmResponse)
async def confirm_customer_password_reset(payload: CustomerPasswordResetConfirmRequest):
    doc = await _get_customer_password_reset_challenge(payload.challenge_id)
    await verify_otp(otp_hash=doc.get("otp_hash") or "", code=payload.code)
    await get_customer_password_reset_challenges_collection().update_one(
        {"_id": doc["_id"]}, {"$set": {"verified": True}},
    )
    return CustomerPasswordResetConfirmResponse(
        challenge_id=payload.challenge_id,
        message="Identidad confirmada. Elige una nueva contraseña.",
    )


@router.post("/password-reset/complete", response_model=CustomerPasswordResetCompleteResponse)
async def complete_customer_password_reset(payload: CustomerPasswordResetCompleteRequest):
    doc = await _get_customer_password_reset_challenge(payload.challenge_id)
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


@router.post("/me/profile-photo", response_model=CustomerPublic)
async def upload_customer_photo(photo: UploadFile = File(...), customer_payload: dict = Depends(require_customer)):
    collection = get_customers_collection()
    doc = await collection.find_one({"_id": ObjectId(customer_payload["customer_id"])})
    if not doc:
        raise HTTPException(status_code=401, detail="La cuenta de cliente ya no existe.")
    content, content_type = await read_image_upload(photo)
    image = await store_image(content, content_type, scope="profiles", owner_id=customer_payload["customer_id"])
    await collection.update_one({"_id": doc["_id"]}, {"$set": {"profile_photo_url": image.url}})
    old_url = doc.get("profile_photo_url")
    if old_url:
        await remove_image(old_url)
    return await get_my_customer(customer_payload)


@router.post("/me/addresses", response_model=CustomerPublic)
async def add_customer_address(payload: CustomerAddressRequest, customer_payload: dict = Depends(require_customer)):
    address = {"id": str(uuid.uuid4()), **payload.model_dump()}
    collection = get_customers_collection()
    await collection.update_one({"_id": ObjectId(customer_payload["customer_id"])}, {"$push": {"addresses": address}})
    return await get_my_customer(customer_payload)


@router.put("/me/addresses/{address_id}", response_model=CustomerPublic)
async def update_customer_address(
    address_id: str,
    payload: CustomerAddressRequest,
    customer_payload: dict = Depends(require_customer),
):
    result = await get_customers_collection().update_one(
        {
            "_id": ObjectId(customer_payload["customer_id"]),
            "addresses.id": address_id,
        },
        {"$set": {f"addresses.$.{field}": value for field, value in payload.model_dump().items()}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="No encontramos esa dirección guardada.")
    return await get_my_customer(customer_payload)


@router.delete("/me/addresses/{address_id}", response_model=CustomerPublic)
async def delete_customer_address(address_id: str, customer_payload: dict = Depends(require_customer)):
    await get_customers_collection().update_one(
        {"_id": ObjectId(customer_payload["customer_id"])},
        {"$pull": {"addresses": {"id": address_id}}},
    )
    return await get_my_customer(customer_payload)


@router.put("/me/favorites/{product_id}", response_model=CustomerPublic)
async def add_customer_favorite(product_id: str, customer_payload: dict = Depends(require_customer)):
    try:
        product_oid = ObjectId(product_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Producto no encontrado.") from exc
    product = await get_catalog_products_collection().find_one({"_id": product_oid})
    if product is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    seller = None
    try:
        seller = await get_registrations_collection().find_one({"_id": ObjectId(str(product.get("seller_id")))})
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
        {"_id": ObjectId(customer_payload["customer_id"])},
        {"$addToSet": {"favorite_product_ids": product_id, "favorites": snapshot}},
    )
    return await get_my_customer(customer_payload)


@router.delete("/me/favorites/{product_id}", response_model=CustomerPublic)
async def remove_customer_favorite(product_id: str, customer_payload: dict = Depends(require_customer)):
    await get_customers_collection().update_one(
        {"_id": ObjectId(customer_payload["customer_id"])},
        {"$pull": {"favorite_product_ids": product_id, "favorites": {"id": product_id}}},
    )
    return await get_my_customer(customer_payload)


@router.get("/me/orders")
async def list_customer_orders(customer_payload: dict = Depends(require_customer)):
    docs = await get_orders_collection().find({"buyer_id": customer_payload["customer_id"]}).sort("created_at", -1).to_list(length=None)
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
            {"_id": {"$in": list(product_ids)}},
            {"image_url": 1, "images": 1},
        ).to_list(length=len(product_ids))
        products_by_id = {str(product["_id"]): product for product in products}

    def items_with_images(doc):
        items = []
        for item in doc.get("items") or []:
            item_data = dict(item)
            product = products_by_id.get(str(item_data.get("product_id") or ""), {})
            images = product.get("images") or []
            primary_image = next(
                (image for image in images if isinstance(image, dict) and image.get("is_frontal") and image.get("image_url")),
                None,
            )
            any_image = next(
                (image for image in images if isinstance(image, dict) and image.get("image_url")),
                None,
            )
            item_data["image_url"] = (primary_image or any_image or {}).get("image_url") or product.get("image_url") or ""
            items.append(item_data)
        return items

    return [
        {
            "id": str(doc["_id"]),
            "store_id": doc["seller_id"],
            "store_name": doc["store_name"],
            "status": doc["status"],
            "items": items_with_images(doc),
            "subtotals": doc.get("subtotals") or [],
            "delivery_requested": bool(doc.get("delivery_requested")),
            "delivery_price": doc.get("delivery_price"),
            "delivery_currency": doc.get("delivery_currency"),
            "created_at": doc["created_at"],
            "updated_at": doc["updated_at"],
            "completed_at": doc.get("completed_at"),
        }
        for doc in docs
    ]


@router.get("/store/customers")
async def list_store_customers(seller_payload: dict = Depends(require_seller)):
    orders = await get_orders_collection().find(
        {"seller_id": seller_payload["seller_id"], "buyer_id": {"$exists": True}}
    ).sort("created_at", -1).to_list(length=None)
    summaries: dict[str, dict[str, Any]] = {}
    for order in orders:
        buyer_id = str(order.get("buyer_id") or "")
        if not buyer_id:
            continue
        summary = summaries.setdefault(
            buyer_id,
            {
                "id": buyer_id,
                "full_name": order.get("buyer_name") or "Cliente",
                "email": order.get("buyer_email") or "",
                "phone": order.get("buyer_phone") or "",
                "orders_count": 0,
                "last_order_at": order.get("created_at"),
                "orders": [],
            },
        )
        summary["orders_count"] += 1
        summary["orders"].append(
            {
                "id": str(order["_id"]),
                "status": order["status"],
                "created_at": order["created_at"],
                "subtotals": order.get("subtotals") or [],
            }
        )
    return list(summaries.values())
