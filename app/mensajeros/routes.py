from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.auth.utils import require_active_seller, require_customer, require_mensajero
from app.catalogs.media_storage import read_image_upload, store_image
from app.mensajeros import service
from app.mensajeros.devices import register_device
from app.mensajeros.schemas import (
    AssignBatchRequest,
    CustomerLocationRequest,
    DeviceRegister,
    EvidenceRequest,
    MensajeroCreate,
    MensajeroLoginRequest,
    MensajeroSetupRequest,
    StartRouteRequest,
    TelemetryPoint,
)
from app.payments.schema import QvaPayAccountRequest
router = APIRouter()
seller_router = APIRouter(prefix="/api/auth/me/mensajeros", tags=["mensajeros"])
panel_router = APIRouter(prefix="/api/mensajeros", tags=["mensajeros"])


@seller_router.get("")
async def list_mensajeros(search: str = "", vehicle_type: str = "", seller: dict = Depends(require_active_seller)):
    return {"items": await service.list_for_seller(seller["seller_id"], search=search, vehicle_type=vehicle_type)}


@seller_router.post("")
async def create_mensajero(payload: MensajeroCreate, seller: dict = Depends(require_active_seller)):
    return await service.create_for_seller(seller["seller_id"], payload)


@seller_router.put("/{mensajero_id}")
async def update_mensajero(mensajero_id: str, payload: MensajeroCreate, seller: dict = Depends(require_active_seller)):
    return await service.update_for_seller(seller["seller_id"], mensajero_id, payload)


@seller_router.delete("/{mensajero_id}")
async def delete_mensajero(mensajero_id: str, seller: dict = Depends(require_active_seller)):
    await service.delete_for_seller(seller["seller_id"], mensajero_id)
    return {"ok": True}


@seller_router.post("/batches")
async def create_batch(payload: AssignBatchRequest, seller: dict = Depends(require_active_seller)):
    return await service.assign_batch(seller["seller_id"], payload)


@seller_router.delete("/orders/{order_id}")
async def cancel_order_assignment(order_id: str, seller: dict = Depends(require_active_seller)):
    return await service.cancel_assignment(seller["seller_id"], order_id)


@seller_router.get("/orders/{order_id}/tracking")
async def seller_tracking(order_id: str, seller: dict = Depends(require_active_seller)):
    return await service.tracking_for(order_id, seller_id=seller["seller_id"])


@panel_router.post("/login")
async def login(payload: MensajeroLoginRequest):
    return await service.login(payload.username, payload.password)


@panel_router.post("/setup")
async def setup(payload: MensajeroSetupRequest):
    return await service.complete_setup(payload.setup_token, payload.password)


@panel_router.get("/me")
async def me(mensajero: dict = Depends(require_mensajero)):
    doc = await service.assert_mensajero_active(mensajero["mensajero_id"])
    from app.mensajeros.service import _public
    return _public(doc)


@panel_router.get("/me/summary")
async def summary(start: str | None = None, end: str | None = None, mensajero: dict = Depends(require_mensajero)):
    from datetime import datetime
    parsed_start = datetime.fromisoformat(start) if start else None
    parsed_end = datetime.fromisoformat(end) if end else None
    return await service.summary_for_messenger(mensajero["mensajero_id"], start=parsed_start, end=parsed_end)


@panel_router.post("/me/devices")
async def save_device(payload: DeviceRegister, mensajero: dict = Depends(require_mensajero)):
    await register_device(mensajero["mensajero_id"], payload.token, payload.platform)
    return {"ok": True}


@panel_router.post("/me/photo")
async def photo(file: UploadFile = File(...), mensajero: dict = Depends(require_mensajero)):
    content, content_type = await read_image_upload(file)
    stored = await store_image(content, content_type, scope="mensajeros", owner_id=mensajero["mensajero_id"])
    return await service.set_profile_photo(mensajero["mensajero_id"], stored.url)


async def _stored_photos(files: list[UploadFile], owner_id: str, *, scope: str) -> list[str]:
    urls = []
    for file in files:
        if not file.filename:
            continue
        content, content_type = await read_image_upload(file)
        stored = await store_image(content, content_type, scope=scope, owner_id=owner_id)
        urls.append(stored.url)
    return urls


@panel_router.post("/me/vehicles")
async def vehicle(
    vehicle_type: str = Form(...),
    plate: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    mensajero: dict = Depends(require_mensajero),
):
    urls = await _stored_photos(files, mensajero["mensajero_id"], scope="mensajeros")
    return await service.add_vehicle(mensajero["mensajero_id"], vehicle_type, plate, urls)


@panel_router.put("/me/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: str,
    vehicle_type: str = Form(...),
    plate: str = Form(""),
    keep_urls: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
    mensajero: dict = Depends(require_mensajero),
):
    uploaded = await _stored_photos(files, mensajero["mensajero_id"], scope="mensajeros")
    return await service.update_vehicle(
        mensajero["mensajero_id"],
        vehicle_id,
        vehicle_type,
        plate,
        keep_urls,
        uploaded,
    )


@panel_router.delete("/me/vehicles/{vehicle_id}")
async def delete_vehicle(vehicle_id: str, mensajero: dict = Depends(require_mensajero)):
    return await service.delete_vehicle(mensajero["mensajero_id"], vehicle_id)


@panel_router.put("/me/qvapay")
async def qvapay(payload: QvaPayAccountRequest, mensajero: dict = Depends(require_mensajero)):
    return await service.set_qvapay(
        mensajero["mensajero_id"],
        payload.username,
        skip_verification_on_service_error=payload.skip_verification,
    )


@panel_router.delete("/me/qvapay")
async def delete_qvapay(mensajero: dict = Depends(require_mensajero)):
    return await service.delete_qvapay(mensajero["mensajero_id"])


@panel_router.post("/batches/{batch_id}/read")
async def read_notice(batch_id: str, mensajero: dict = Depends(require_mensajero)):
    return await service.mark_notice_read(mensajero["mensajero_id"], batch_id)


@panel_router.post("/batches/{batch_id}/start")
async def start(batch_id: str, payload: StartRouteRequest, mensajero: dict = Depends(require_mensajero)):
    return await service.start_route(mensajero["mensajero_id"], batch_id, payload.vehicle_id, payload.client_id)


@panel_router.post("/batches/{batch_id}/points")
async def point(batch_id: str, payload: TelemetryPoint, mensajero: dict = Depends(require_mensajero)):
    return await service.add_point(mensajero["mensajero_id"], batch_id, payload)


@seller_router.get("/orders/{order_id}/evidence.pdf")
async def seller_courier_evidence_pdf(order_id: str, seller: dict = Depends(require_active_seller)):
    pdf_bytes, filename = await service.courier_evidence_pdf(order_id, seller_id=seller["seller_id"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@panel_router.get("/orders/{order_id}/evidence.pdf")
async def messenger_courier_evidence_pdf(order_id: str, mensajero: dict = Depends(require_mensajero)):
    pdf_bytes, filename = await service.courier_evidence_pdf(order_id, mensajero_id=mensajero["mensajero_id"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@panel_router.post("/orders/{order_id}/evidence")
async def evidence(
    order_id: str,
    note: str = Form(""),
    client_id: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    mensajero: dict = Depends(require_mensajero),
):
    urls = []
    for file in files:
        if not file.filename:
            continue
        content, content_type = await read_image_upload(file)
        stored = await store_image(content, content_type, scope="order-evidence", owner_id=mensajero["mensajero_id"])
        urls.append(stored.url)
    return await service.submit_evidence(
        mensajero["mensajero_id"],
        order_id,
        note=note,
        image_urls=urls,
        client_id=client_id,
    )


@panel_router.post("/orders/{order_id}/location")
async def customer_location(order_id: str, payload: CustomerLocationRequest, customer: dict = Depends(require_customer)):
    return await service.save_customer_location(customer["customer_id"], order_id, payload.lat, payload.lng)


@panel_router.get("/orders/{order_id}/tracking")
async def customer_tracking(order_id: str, customer: dict = Depends(require_customer)):
    return await service.tracking_for(order_id, customer_id=customer["customer_id"])


router.include_router(seller_router)
router.include_router(panel_router)
