from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field


class CreateEventRequest(BaseModel):
    event_id: str = Field(min_length=2, max_length=100)
    event_name: str = Field(min_length=2, max_length=200)
    event_date: datetime
    capacity: int = Field(default=500, ge=1)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    event_name: str
    event_date: datetime
    capacity: int
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
