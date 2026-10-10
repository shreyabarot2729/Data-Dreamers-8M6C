from __future__ import annotations

from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import qrcode
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.admin_api import router as admin_router
from app.database import (
    Base,
    create_db_engine,
    create_session_factory,
    upgrade_legacy_sqlite_schema,
)
from app.deps import get_admin_user, get_service
from app.schemas import (
    AdminAuthResponse,
    AdminDashboardResponse,
    AdminLoginRequest,
    AdminUserResponse,
    BiometricVerificationResponse,
    CheckInRequest,
    CheckInResponse,
    CreateEventRequest,
    CreateRegistrationRequest,
    EventResponse,
    OtpRequest,
    ParticipantResponse,
    RegistrationResponse,
    VerificationRequest,
)
from app.services import RegistrationService


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_db_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_legacy_sqlite_schema)
    session_factory = create_session_factory(engine)
    init_service = RegistrationService(session_factory)
    await init_service.seed_default_events()
    await init_service.seed_default_admin()
    await init_service.close()
    app.state.engine = engine
    app.state.session_factory = session_factory
    yield
    await app.state.engine.dispose()


app = FastAPI(title="Event Registration & Biometric System", lifespan=lifespan)
APP_DIRECTORY = Path(__file__).resolve().parent
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=APP_DIRECTORY / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = APP_DIRECTORY / "templates" / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>EventSecure System</h1>")


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/{admin_path:path}", response_class=HTMLResponse)
async def admin_panel(admin_path: str = ""):
    del admin_path
    html_file = APP_DIRECTORY / "templates" / "admin.html"
    if not html_file.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin panel not found")
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.post("/api/admin/login", response_model=AdminAuthResponse)
async def admin_login(
    payload: AdminLoginRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        admin = await service.authenticate_admin(payload.identifier, payload.password, payload.mfa_code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token = service._build_admin_token(admin)
    return AdminAuthResponse(
        token=token,
        user=AdminUserResponse(
            id=admin.id,
            username=admin.username,
            email=admin.email,
            role=admin.role,
            is_active=admin.is_active,
            mfa_enabled=admin.mfa_enabled,
            last_login_at=admin.last_login_at,
        ),
    )


@app.get("/api/admin/me", response_model=AdminUserResponse)
async def admin_me(
    admin=Depends(get_admin_user),
):
    return AdminUserResponse(
        id=admin.id,
        username=admin.username,
        email=admin.email,
        role=admin.role,
        is_active=admin.is_active,
        mfa_enabled=admin.mfa_enabled,
        last_login_at=admin.last_login_at,
    )


@app.get("/api/admin/dashboard", response_model=AdminDashboardResponse)
async def admin_dashboard(
    service: RegistrationService = Depends(get_service),
    admin=Depends(get_admin_user),
):
    del admin
    summary = await service.get_admin_dashboard()
    return AdminDashboardResponse(**summary)


@app.get("/api/events", response_model=list[EventResponse])
async def list_events(service: RegistrationService = Depends(get_service)):
    events = await service.get_events()
    return events


@app.post("/api/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: CreateEventRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        event = await service.create_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return event


@app.get("/api/participants", response_model=list[ParticipantResponse])
async def list_participants(service: RegistrationService = Depends(get_service)):
    participants = await service.get_participants()
    return participants


@app.get("/api/registrations", response_model=list[RegistrationResponse])
async def list_registrations(service: RegistrationService = Depends(get_service)):
    return await service.get_registrations()


@app.get("/api/biometrics", response_model=list[BiometricVerificationResponse])
async def list_biometrics(
    participant_id: str | None = None,
    service: RegistrationService = Depends(get_service),
):
    records = await service.get_biometrics(participant_id=participant_id)
    return records


@app.post(
    "/api/registrations",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_registration(
    payload: CreateRegistrationRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.create_registration(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return registration


@app.get("/api/registrations/{registration_id}", response_model=RegistrationResponse)
async def get_registration(
    registration_id: int,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service._load_registration(registration_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return registration


@app.post("/api/registrations/{registration_id}/otp", response_model=RegistrationResponse)
async def verify_otp(
    registration_id: int,
    request: OtpRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.verify_otp(registration_id, request.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return registration


@app.post("/api/registrations/{registration_id}/face", response_model=RegistrationResponse)
async def verify_face(
    registration_id: int,
    request: VerificationRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.verify_face(registration_id, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return registration


@app.post("/api/registrations/{registration_id}/liveness", response_model=RegistrationResponse)
async def verify_liveness(
    registration_id: int,
    request: VerificationRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.verify_liveness(registration_id, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return registration


@app.post("/api/registrations/{registration_id}/pad", response_model=RegistrationResponse)
async def verify_pad(
    registration_id: int,
    request: VerificationRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.verify_pad(registration_id, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return registration


@app.post("/api/registrations/{registration_id}/complete", response_model=RegistrationResponse)
async def complete_registration(
    registration_id: int,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.complete_registration(registration_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return registration


@app.get("/api/registrations/{registration_id}/qr")
async def registration_qr(
    registration_id: int,
    service: RegistrationService = Depends(get_service),
):
    try:
        qr_data = await service.get_qr_code(registration_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@app.post("/api/check-in", response_model=CheckInResponse)
async def check_in(
    request: CheckInRequest,
    service: RegistrationService = Depends(get_service),
):
    try:
        registration = await service.check_in(
            registration_id=request.registration_id,
            face_payload=request.face_payload,
            qr_token=request.qr_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    full_name = f"{registration.first_name} {registration.last_name}".strip()
    part_type = (
        registration.participant.participant_type
        if registration.participant
        else "Attendee"
    )
    org = (
        registration.participant.organization
        if registration.participant
        else "Individual"
    )

    return CheckInResponse(
        success=True,
        message=f"Access Granted! Welcome {full_name}.",
        status=registration.status,
        participant_id=registration.participant_id,
        full_name=full_name,
        event_id=registration.event_id,
        participant_type=part_type,
        organization=org,
        checked_in_at=registration.checked_in_at,
        registration_id=registration.id,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
