from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import AdminUser
from app.deps import get_admin_user, get_service
from app.schemas import (
    AdminCheckInRequest,
    AdminUserResponse,
    AuditLogResponse,
    BiometricReviewRequest,
    BiometricVerificationResponse,
    CheckInResponse,
    CreateAdminUserRequest,
    CreateEventRequest,
    EventResponse,
    ParticipantResponse,
    QrPassResponse,
    RegistrationResponse,
    ReportsSummaryResponse,
    SystemSettingsResponse,
    UpdateEventRequest,
    UpdateRegistrationStatusRequest,
)
from app.config import settings
from app.services import RegistrationService


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _registration_response(registration) -> RegistrationResponse:
    participant_type = "Attendee"
    organization = "Individual"
    if registration.participant:
        participant_type = registration.participant.participant_type
        organization = registration.participant.organization
    return RegistrationResponse(
        id=registration.id,
        registration_id=registration.registration_id,
        event_id=registration.event_id,
        participant_id=registration.participant_id,
        first_name=registration.first_name,
        last_name=registration.last_name,
        email=registration.email,
        mobile=registration.mobile,
        status=registration.status,
        otp_code=registration.otp_code,
        otp_expires_at=registration.otp_expires_at,
        face_verified=registration.face_verified,
        liveness_verified=registration.liveness_verified,
        pad_verified=registration.pad_verified,
        qr_code=registration.qr_token,
        qr_token=registration.qr_token,
        registered_at=registration.registered_at,
        checked_in_at=registration.checked_in_at,
        created_at=registration.created_at,
        updated_at=registration.updated_at,
        participant_type=participant_type,
        organization=organization,
    )


async def _event_response(service: RegistrationService, event_id: str) -> EventResponse:
    events = await service.get_events()
    for item in events:
        if item["event_id"] == event_id:
            return EventResponse(**item)
    event = await service.get_event_by_code(event_id)
    return EventResponse(
        id=event.id,
        event_id=event.event_id,
        event_name=event.event_name,
        event_date=event.event_date,
        venue=getattr(event, "venue", "") or "",
        capacity=event.capacity,
        registration_start=getattr(event, "registration_start", None),
        registration_end=getattr(event, "registration_end", None),
        participant_types=getattr(event, "participant_types", "Attendee,Speaker,VIP,Organizer,Delegate"),
        verification_requirements=getattr(event, "verification_requirements", "otp,face,liveness,pad"),
        status=getattr(event, "status", "published"),
        created_at=event.created_at,
        registered_count=0,
    )


def require_role(*roles: str):
    async def _dependency(admin: AdminUser = Depends(get_admin_user)) -> AdminUser:
        if admin.role not in roles and admin.role != "super_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return admin

    return _dependency


@router.get("/events", response_model=list[EventResponse])
async def admin_list_events(
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    events = await service.get_events()
    return [EventResponse(**item) for item in events]


@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_event(
    payload: CreateEventRequest,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "event_manager")),
):
    try:
        event = await service.create_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await service.log_audit(admin, "create_event", "event", event.event_id, payload.event_name)
    return await _event_response(service, event.event_id)


@router.get("/events/{event_id}", response_model=EventResponse)
async def admin_get_event(
    event_id: str,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    try:
        return await _event_response(service, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/events/{event_id}", response_model=EventResponse)
async def admin_update_event(
    event_id: str,
    payload: UpdateEventRequest,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "event_manager")),
):
    try:
        await service.update_event(event_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await service.log_audit(admin, "update_event", "event", event_id, payload.model_dump_json())
    return await _event_response(service, event_id)


@router.get("/participants", response_model=list[ParticipantResponse])
async def admin_list_participants(
    q: str | None = Query(default=None),
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    if q:
        return await service.search_participants(q)
    return await service.get_participants()


@router.get("/participants/{participant_key}", response_model=ParticipantResponse)
async def admin_get_participant(
    participant_key: str,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    try:
        return await service.get_participant_by_key(participant_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/registrations", response_model=list[RegistrationResponse])
async def admin_list_registrations(
    event_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    rows = await service.filter_registrations(
        event_id=event_id,
        status=status_filter,
        search=q,
        created_from=created_from,
        created_to=created_to,
    )
    return [_registration_response(row) for row in rows]


@router.get("/registrations/{registration_id}", response_model=RegistrationResponse)
async def admin_get_registration(
    registration_id: int,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    try:
        registration = await service._load_registration(registration_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _registration_response(registration)


@router.patch("/registrations/{registration_id}/status", response_model=RegistrationResponse)
async def admin_update_registration_status(
    registration_id: int,
    payload: UpdateRegistrationStatusRequest,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "registration_manager")),
):
    try:
        registration = await service.update_registration_status(
            registration_id, payload.status, payload.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await service.log_audit(
        admin,
        "update_registration_status",
        "registration",
        str(registration_id),
        f"{payload.status}: {payload.reason}",
    )
    return _registration_response(registration)


@router.post("/registrations/{registration_id}/qr/revoke", response_model=RegistrationResponse)
async def admin_revoke_qr(
    registration_id: int,
    reason: str = Query(min_length=3, max_length=500),
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "registration_manager")),
):
    try:
        registration = await service.revoke_qr_pass(registration_id, reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await service.log_audit(admin, "revoke_qr", "registration", str(registration_id), reason)
    return _registration_response(registration)


@router.post("/registrations/{registration_id}/qr/reissue", response_model=RegistrationResponse)
async def admin_reissue_qr(
    registration_id: int,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "registration_manager")),
):
    try:
        registration = await service.reissue_qr_pass(registration_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await service.log_audit(admin, "reissue_qr", "registration", str(registration_id), "")
    return _registration_response(registration)


@router.get("/biometric-verifications", response_model=list[BiometricVerificationResponse])
async def admin_list_biometrics(
    participant_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    records = await service.get_biometrics(participant_id=participant_id)
    if q:
        term = q.lower()
        records = [
            item
            for item in records
            if term in item.verification_id.lower() or term in item.participant_id.lower()
        ]
    return records


@router.post(
    "/biometric-verifications/{verification_id}/review",
    response_model=BiometricVerificationResponse,
)
async def admin_review_biometric(
    verification_id: str,
    payload: BiometricReviewRequest,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "biometric_reviewer")),
):
    try:
        record = await service.review_biometric(
            verification_id,
            payload.decision,
            payload.reason,
            payload.registration_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await service.log_audit(
        admin,
        "review_biometric",
        "biometric",
        verification_id,
        f"{payload.decision}: {payload.reason}",
    )
    return record


@router.get("/qr-passes", response_model=list[QrPassResponse])
async def admin_list_qr_passes(
    q: str | None = Query(default=None),
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    rows = await service.list_qr_passes(search=q)
    return [QrPassResponse(**row) for row in rows]


@router.post("/check-in", response_model=CheckInResponse)
async def admin_check_in(
    payload: AdminCheckInRequest,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "gate_operator")),
):
    if payload.skip_face and not payload.override_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A reason is required for a manual face-verification override",
        )
    try:
        registration = await service.admin_check_in(
            admin=admin,
            qr_token=payload.qr_token,
            registration_id=payload.registration_id,
            event_id=payload.event_id,
            gate=payload.gate,
            face_payload=payload.face_payload or "",
            skip_face=payload.skip_face,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await service.log_audit(
        admin,
        "check_in",
        "registration",
        str(registration.id),
        f"gate={payload.gate}; skip_face={payload.skip_face}; "
        f"override_reason={payload.override_reason or ''}",
    )
    full_name = f"{registration.first_name} {registration.last_name}".strip()
    part_type = registration.participant.participant_type if registration.participant else "Attendee"
    org = registration.participant.organization if registration.participant else "Individual"
    return CheckInResponse(
        success=True,
        message=f"Check-in confirmed for {full_name}",
        status=registration.status,
        participant_id=registration.participant_id,
        full_name=full_name,
        event_id=registration.event_id,
        participant_type=part_type,
        organization=org,
        checked_in_at=registration.checked_in_at,
        registration_id=registration.id,
    )


@router.get("/reports/summary", response_model=ReportsSummaryResponse)
async def admin_reports_summary(
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(get_admin_user),
):
    del admin
    summary = await service.get_reports_summary()
    return ReportsSummaryResponse(**summary)


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def admin_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin", "auditor")),
):
    del admin
    return await service.get_audit_logs(limit=limit)


@router.get("/settings", response_model=SystemSettingsResponse)
async def admin_settings(
    admin: AdminUser = Depends(require_role("super_admin")),
):
    del admin
    return SystemSettingsResponse(
        app_env=settings.app_env,
        otp_provider=settings.otp_provider,
        face_provider=settings.face_provider,
        verify_face=settings.verify_face,
        verify_liveness=settings.verify_liveness,
        verify_pad=settings.verify_pad,
        admin_mfa_required=settings.admin_mfa_required,
        app_url=settings.app_url,
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def admin_users(
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin")),
):
    del admin
    users = await service.list_admin_users()
    return [
        AdminUserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            mfa_enabled=user.mfa_enabled,
            last_login_at=user.last_login_at,
        )
        for user in users
    ]


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    payload: CreateAdminUserRequest,
    service: RegistrationService = Depends(get_service),
    admin: AdminUser = Depends(require_role("super_admin")),
):
    try:
        user = await service.create_admin_user(
            username=payload.username,
            email=str(payload.email),
            password=payload.password,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await service.log_audit(admin, "create_admin_user", "admin_user", str(user.id), user.role)
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        last_login_at=user.last_login_at,
    )
