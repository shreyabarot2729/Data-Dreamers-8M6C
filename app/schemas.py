from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field


class CreateEventRequest(BaseModel):
    event_id: str = Field(min_length=2, max_length=100)
    event_name: str = Field(min_length=2, max_length=200)
    event_date: datetime
    venue: str = Field(default="", max_length=300)
    capacity: int = Field(default=500, ge=1)
    registration_start: datetime | None = None
    registration_end: datetime | None = None
    participant_types: str = Field(default="Attendee,Speaker,VIP,Organizer,Delegate", max_length=500)
    verification_requirements: str = Field(default="otp,face,liveness,pad", max_length=200)
    status: str = Field(default="draft", max_length=50)


class UpdateEventRequest(BaseModel):
    event_name: str | None = Field(default=None, min_length=2, max_length=200)
    event_date: datetime | None = None
    venue: str | None = Field(default=None, max_length=300)
    capacity: int | None = Field(default=None, ge=1)
    registration_start: datetime | None = None
    registration_end: datetime | None = None
    participant_types: str | None = Field(default=None, max_length=500)
    verification_requirements: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=50)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    event_name: str
    event_date: datetime
    venue: str = ""
    capacity: int
    registration_start: datetime | None = None
    registration_end: datetime | None = None
    participant_types: str = "Attendee,Speaker,VIP,Organizer,Delegate"
    verification_requirements: str = "otp,face,liveness,pad"
    status: str = "published"
    created_at: datetime
    registered_count: int = 0


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    participant_id: str
    full_name: str
    email: str
    mobile: str
    participant_type: str
    organization: str
    created_at: datetime


class BiometricVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    verification_id: str
    participant_id: str
    provider_reference: str
    face_verified: bool
    liveness_verified: bool
    pad_verified: bool
    iris_verified: bool
    fingerprint_verified: bool
    consent_id: str
    verified_at: datetime
    liveness_passed: bool = False
    verification_date: datetime | None = None


class CreateRegistrationRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=200)
    email: EmailStr
    mobile: str = Field(min_length=6, max_length=25)
    participant_type: str = Field(default="Attendee", max_length=50)
    organization: str = Field(default="Individual", max_length=150)
    consent_agreed: bool = Field(default=True)


class RegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    registration_id: str = ""
    event_id: str
    participant_id: str
    first_name: str
    last_name: str
    email: str
    mobile: str
    status: str
    otp_code: str | None = None
    otp_expires_at: datetime
    face_verified: bool
    liveness_verified: bool
    pad_verified: bool
    qr_code: str | None = None
    qr_token: str | None = None
    registered_at: datetime | None = None
    checked_in_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    participant_type: str = "Attendee"
    organization: str = "Individual"

    @computed_field
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join([p for p in parts if p]).strip() or "Participant"


class OtpRequest(BaseModel):
    code: str = Field(min_length=1)


class VerificationRequest(BaseModel):
    payload: str = Field(min_length=1)


class CheckInRequest(BaseModel):
    registration_id: int | None = None
    qr_token: str | None = None
    face_payload: str = Field(default="valid-face")


class AdminLoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=4, max_length=200)
    mfa_code: str | None = Field(default=None, min_length=4, max_length=12)


class CreateAdminUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    role: str = Field(pattern="^(super_admin|event_manager|registration_manager|biometric_reviewer|gate_operator|auditor)$")


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None = None


class AdminAuthResponse(BaseModel):
    token: str
    user: AdminUserResponse


class AdminDashboardResponse(BaseModel):
    total_events: int
    total_participants: int
    total_registrations: int
    pending_otp_verification: int
    pending_biometric_verification: int
    verified_participants: int
    qr_passes_issued: int
    today_checkins: int
    failed_verification_attempts: int
    recent_activity: list[str]


class CheckInResponse(BaseModel):
    success: bool
    message: str
    status: str
    participant_id: str
    full_name: str
    event_id: str
    participant_type: str
    organization: str
    checked_in_at: datetime
    registration_id: int


class UpdateRegistrationStatusRequest(BaseModel):
    status: str = Field(min_length=3, max_length=50)
    reason: str = Field(min_length=3, max_length=500)


class BiometricReviewRequest(BaseModel):
    decision: str = Field(min_length=3, max_length=50)
    reason: str = Field(min_length=3, max_length=500)
    registration_id: int | None = None


class AdminCheckInRequest(BaseModel):
    qr_token: str | None = None
    registration_id: int | None = None
    event_id: str | None = None
    gate: str = Field(default="main", max_length=100)
    face_payload: str | None = None
    skip_face: bool = False
    override_reason: str | None = Field(default=None, min_length=3, max_length=500)


class QrPassResponse(BaseModel):
    registration_id: int
    registration_code: str
    participant_id: str
    event_id: str
    full_name: str
    status: str
    qr_token: str | None
    revoked: bool
    registered_at: datetime | None
    checked_in_at: datetime | None


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_id: int | None
    admin_username: str
    action: str
    entity_type: str
    entity_id: str
    details: str
    created_at: datetime


class SystemSettingsResponse(BaseModel):
    app_env: str
    otp_provider: str
    face_provider: str
    verify_face: bool
    verify_liveness: bool
    verify_pad: bool
    admin_mfa_required: bool
    app_url: str


class ReportsSummaryResponse(BaseModel):
    events_by_status: dict[str, int]
    registrations_by_status: dict[str, int]
    verification_pass_rate: float
    capacity_utilization: list[dict[str, float | str | int]]
