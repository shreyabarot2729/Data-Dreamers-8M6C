from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import (
    BiometricVerification,
    Event,
    Participant,
    ParticipantAddress,
    Registration,
)
from app.providers import (
    LocalFaceProvider,
    VerificationProviderFactory,
    generate_consent_id,
    generate_otp,
    generate_participant_id,
    generate_provider_reference,
    generate_registration_id,
    generate_verification_id,
)
from app.schemas import CreateEventRequest, CreateRegistrationRequest


class VerificationStatus(StrEnum):
    OTP_PENDING = "otp_pending"
    FACE_PENDING = "face_pending"
    LIVENESS_PENDING = "liveness_pending"
    PAD_PENDING = "pad_pending"
    REGISTERED = "registered"
    CHECKED_IN = "checked_in"
    REJECTED = "rejected"


@dataclass
class RegistrationService:
    session_factory: async_sessionmaker
    providers: VerificationProviderFactory = VerificationProviderFactory()

    def __post_init__(self):
        self.session: AsyncSession | None = None

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = self.session_factory()
        return self.session

    async def seed_default_events(self) -> None:
        session = await self._get_session()
        result = await session.execute(select(func.count(Event.id)))
        count = result.scalar() or 0
        if count == 0:
            default_events = [
                Event(
                    event_id="EVT-2026-001",
                    event_name="Global AI & Cyber Security Summit 2026",
                    event_date=datetime.now(UTC) + timedelta(days=30),
                    capacity=500,
                ),
                Event(
                    event_id="EVT-2026-002",
                    event_name="National Tech Innovators Conference",
                    event_date=datetime.now(UTC) + timedelta(days=45),
                    capacity=300,
                ),
                Event(
                    event_id="EVT-2026-003",
                    event_name="Developer Hackathon 2026",
                    event_date=datetime.now(UTC) + timedelta(days=15),
                    capacity=150,
                ),
            ]
            for ev in default_events:
                session.add(ev)
            await session.commit()

    async def _ensure_event_exists(self, event_id: str) -> Event:
        session = await self._get_session()
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if event is None:
            event = Event(
                event_id=event_id,
                event_name=f"Event {event_id}",
                event_date=datetime.now(UTC) + timedelta(days=30),
                capacity=500,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
        return event

    async def get_events(self) -> list[dict]:
        session = await self._get_session()
        await self.seed_default_events()
        result = await session.execute(select(Event).order_by(Event.id))
        events = result.scalars().all()
        data = []
        for ev in events:
            reg_count_res = await session.execute(
                select(func.count(Registration.id)).where(
                    Registration.event_id == ev.event_id,
                    Registration.status.in_(
                        {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}
                    ),
                )
            )
            reg_count = reg_count_res.scalar() or 0
            data.append(
                {
                    "id": ev.id,
                    "event_id": ev.event_id,
                    "event_name": ev.event_name,
                    "event_date": ev.event_date,
                    "capacity": ev.capacity,
                    "created_at": ev.created_at,
                    "registered_count": reg_count,
                }
            )
        return data

    async def create_event(self, request: CreateEventRequest) -> Event:
        session = await self._get_session()
        existing = await session.execute(select(Event).where(Event.event_id == request.event_id))
        if existing.scalar_one_or_none():
            raise ValueError(f"Event with ID '{request.event_id}' already exists")
        event = Event(
            event_id=request.event_id,
            event_name=request.event_name,
            event_date=request.event_date,
            capacity=request.capacity,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    async def get_participants(self) -> list[Participant]:
        session = await self._get_session()
        result = await session.execute(select(Participant).order_by(Participant.id.desc()))
        return list(result.scalars().all())

    async def get_participant_addresses(self) -> list[ParticipantAddress]:
        session = await self._get_session()
        result = await session.execute(
            select(ParticipantAddress).order_by(ParticipantAddress.id.desc())
        )
        return list(result.scalars().all())

    async def get_biometrics(
        self, participant_id: str | None = None
    ) -> list[BiometricVerification]:
        session = await self._get_session()
        query = select(BiometricVerification).order_by(BiometricVerification.id.desc())
        if participant_id:
            query = query.where(BiometricVerification.participant_id == participant_id)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_registrations(self) -> list[Registration]:
        session = await self._get_session()
        result = await session.execute(select(Registration).order_by(Registration.id.desc()))
        return list(result.scalars().all())

    async def is_duplicate_registration(self, event_id: str, email: str) -> bool:
        session = await self._get_session()
        result = await session.execute(
            select(Registration.id).where(
                Registration.event_id == event_id,
                Registration.email == email,
                Registration.status.in_(
                    {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_registration(self, request: CreateRegistrationRequest) -> Registration:
        session = await self._get_session()
        email_str = str(request.email).strip().lower()

        # Step: Check duplicate event registration
        if await self.is_duplicate_registration(request.event_id, email_str):
            raise ValueError("This email is already registered for the event")

        # Step: Ensure Event exists & check capacity
        event = await self._ensure_event_exists(request.event_id)
        reg_count_res = await session.execute(
            select(func.count(Registration.id)).where(
                Registration.event_id == request.event_id,
                Registration.status.in_(
                    {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}
                ),
            )
        )
        current_registered = reg_count_res.scalar() or 0
        if current_registered >= event.capacity:
            raise ValueError(f"Event '{event.event_name}' capacity ({event.capacity}) reached")

        # Parse name fields
        first_name = (request.first_name or "").strip()
        last_name = (request.last_name or "").strip()
        if not first_name and request.full_name:
            tokens = request.full_name.strip().split(maxsplit=1)
            first_name = tokens[0]
            last_name = tokens[1] if len(tokens) > 1 else ""
        if not first_name:
            first_name = "Participant"
        full_name = f"{first_name} {last_name}".strip()

        # Step: Participant management
        part_res = await session.execute(select(Participant).where(Participant.email == email_str))
        participant = part_res.scalar_one_or_none()
        if participant is None:
            participant = Participant(
                participant_id=generate_participant_id(),
                full_name=full_name,
                email=email_str,
                mobile=request.mobile,
                participant_type=request.participant_type or "Attendee",
                organization=request.organization or "Individual",
            )
            session.add(participant)
            await session.flush()
        else:
            participant.full_name = full_name
            participant.mobile = request.mobile
            if request.participant_type:
                participant.participant_type = request.participant_type
            if request.organization:
                participant.organization = request.organization
            session.add(participant)
            await session.flush()

        address_fields = tuple(
            value.strip() if value and value.strip() else None
            for value in (
                request.address_line1,
                request.city,
                request.state_province,
                request.country,
                request.postal_code,
            )
        )
        if any(address_fields):
            if not all(address_fields):
                raise ValueError(
                    "Complete the street address, city, state/province, country, and postal code."
                )
            address_result = await session.execute(
                select(ParticipantAddress).where(
                    ParticipantAddress.participant_id == participant.participant_id
                )
            )
            address = address_result.scalar_one_or_none()
            if address is None:
                address = ParticipantAddress(participant_id=participant.participant_id)
            address.address_line1 = address_fields[0]
            address.address_line2 = (request.address_line2 or "").strip() or None
            address.city = address_fields[1]
            address.state_province = address_fields[2]
            address.country = address_fields[3]
            address.postal_code = address_fields[4]
            session.add(address)

        # Step: Issue Email + Mobile OTP
        otp_code = None if self.providers.uses_external_otp else generate_otp()
        otp_secret = secrets.token_urlsafe(16)
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        registration_id = generate_registration_id()

        registration = Registration(
            registration_id=registration_id,
            event_id=request.event_id,
            participant_id=participant.participant_id,
            first_name=first_name,
            last_name=last_name,
            email=email_str,
            mobile=request.mobile,
            status=VerificationStatus.OTP_PENDING,
            otp_code=otp_code,
            otp_secret=otp_secret,
            otp_expires_at=expires_at,
            face_verified=False,
            liveness_verified=False,
            pad_verified=False,
            qr_token=None,
        )
        await self.providers.send_otp(request.mobile)
        session.add(registration)
        try:
            await session.commit()
            await session.refresh(registration)
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("Registration collision; please try again") from exc

        return registration

    async def _load_registration(self, registration_id: int) -> Registration:
        session = await self._get_session()
        registration = await session.get(Registration, registration_id)
        if registration is None:
            raise ValueError("Registration not found")
        return registration

    async def verify_otp(self, registration_id: int, otp_code: str) -> Registration:
        registration = await self._load_registration(registration_id)
        expires_at = registration.otp_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if expires_at < datetime.now(UTC):
            raise ValueError("OTP has expired")
        if not await self.providers.check_otp(
            registration.mobile, otp_code.strip(), registration.otp_code
        ):
            raise ValueError("Invalid OTP")

        registration.status = VerificationStatus.FACE_PENDING
        registration.updated_at = datetime.now(UTC)
        await self._commit(registration)
        return registration

    async def verify_face(self, registration_id: int, face_payload: str) -> Registration:
        registration = await self._load_registration(registration_id)
        if registration.status != VerificationStatus.FACE_PENDING:
            raise ValueError("Face verification is not pending")

        result = await self.providers.verify_face(registration.participant_id, face_payload)
        if not result.accepted:
            raise ValueError(result.message or "Face verification failed")

        if isinstance(self.providers.face, LocalFaceProvider):
            if result.face_template is None:
                raise ValueError("Local face matcher did not return a face template.")
            session = await self._get_session()
            participants = await session.execute(
                select(Participant.participant_id, Participant.face_template).where(
                    Participant.face_template.is_not(None),
                    Participant.participant_id != registration.participant_id,
                )
            )
            for participant_id, template in participants:
                similarity = self.providers.face._cosine_similarity(
                    self.providers.face._parse_template(result.face_template),
                    self.providers.face._parse_template(template),
                )
                if similarity >= self.providers.face.match_threshold:
                    raise ValueError(
                        "This face is already enrolled under another participant. "
                        "Registration blocked."
                    )
            participant_result = await session.execute(
                select(Participant).where(
                    Participant.participant_id == registration.participant_id
                )
            )
            participant = participant_result.scalar_one_or_none()
            if participant is None:
                raise ValueError("Participant not found for local face enrollment.")
            if participant.face_template:
                similarity = self.providers.face._cosine_similarity(
                    self.providers.face._parse_template(result.face_template),
                    self.providers.face._parse_template(participant.face_template),
                )
                if similarity < self.providers.face.match_threshold:
                    raise ValueError(
                        "This registration does not match the participant's enrolled face."
                    )
            else:
                participant.face_template = result.face_template

        registration.face_verified = True
        registration.face_match = result.provider_reference
        registration.status = VerificationStatus.LIVENESS_PENDING
        registration.updated_at = datetime.now(UTC)
        await self._commit(registration)
        return registration

    async def verify_liveness(self, registration_id: int, liveness_payload: str) -> Registration:
        registration = await self._load_registration(registration_id)
        if registration.status != VerificationStatus.LIVENESS_PENDING:
            raise ValueError("Liveness verification is not pending")

        result = await self.providers.verify_liveness(registration.participant_id, liveness_payload)
        if not result.accepted:
            raise ValueError(result.message or "Liveness verification failed")

        registration.liveness_verified = True
        registration.status = VerificationStatus.PAD_PENDING
        registration.updated_at = datetime.now(UTC)
        await self._commit(registration)
        return registration

    async def verify_pad(self, registration_id: int, pad_payload: str) -> Registration:
        registration = await self._load_registration(registration_id)
        if registration.status != VerificationStatus.PAD_PENDING:
            raise ValueError("PAD verification is not pending")

        result = await self.providers.verify_pad(registration.participant_id, pad_payload)
        if not result.accepted:
            raise ValueError(result.message or "PAD verification failed")

        session = await self._get_session()
        registration.pad_verified = True
        registration.updated_at = datetime.now(UTC)

        # Record verified biometrics with consent ID in BiometricVerification table
        biometric_record = BiometricVerification(
            verification_id=generate_verification_id(),
            participant_id=registration.participant_id,
            provider_reference=result.provider_reference or generate_provider_reference(),
            face_verified=True,
            liveness_verified=True,
            pad_verified=True,
            iris_verified=False,
            fingerprint_verified=False,
            consent_id=generate_consent_id(),
            verified_at=datetime.now(UTC),
        )
        session.add(biometric_record)
        await self._commit(registration)
        return registration

    async def complete_registration(self, registration_id: int) -> Registration:
        registration = await self._load_registration(registration_id)
        allowed_statuses = {
            VerificationStatus.PAD_PENDING,
            VerificationStatus.REGISTERED,
        }
        if registration.status not in allowed_statuses:
            raise ValueError("Registration is not ready to complete")

        if not all([
            registration.face_verified,
            registration.liveness_verified,
            registration.pad_verified,
        ]):
            raise ValueError("All identity checks must pass")

        registration.status = VerificationStatus.REGISTERED
        registration.registered_at = datetime.now(UTC)
        registration.qr_token = (
            f"event-registration:{registration.participant_id}:"
            f"{hashlib.sha256(registration.otp_secret.encode()).hexdigest()[:12]}"
        )
        registration.updated_at = datetime.now(UTC)
        await self._commit(registration)
        return registration

    async def get_qr_code(self, registration_id: int) -> str:
        registration = await self._load_registration(registration_id)
        if not registration.qr_token:
            raise ValueError("QR code not available")
        return registration.qr_token

    async def check_in(
        self,
        registration_id: int | None = None,
        face_payload: str = "valid-face",
        qr_token: str | None = None,
    ) -> Registration:
        session = await self._get_session()

        registration = None
        if qr_token:
            token_clean = qr_token.strip()
            # If the user passed raw QR token or participant ID or integer string
            query = select(Registration).where(Registration.qr_token == token_clean)
            res = await session.execute(query)
            registration = res.scalar_one_or_none()
            if registration is None:
                # Try finding by participant_id
                res_part = await session.execute(
                    select(Registration).where(Registration.participant_id == token_clean)
                )
                registration = res_part.scalar_one_or_none()
            if registration is None and token_clean.isdigit():
                registration = await session.get(Registration, int(token_clean))

        if registration is None and registration_id is not None:
            registration = await session.get(Registration, registration_id)

        if registration is None:
            raise ValueError("Registration not found with provided QR or ID")

        if registration.status == VerificationStatus.CHECKED_IN:
            raise ValueError("Registration is already checked in")

        if registration.status != VerificationStatus.REGISTERED:
            status_str = registration.status
            raise ValueError(f"Registration is not confirmed (current status: {status_str})")

        face_template = None
        if isinstance(self.providers.face, LocalFaceProvider):
            participant_result = await session.execute(
                select(Participant.face_template).where(
                    Participant.participant_id == registration.participant_id
                )
            )
            participant = participant_result.scalar_one_or_none()
            face_template = participant
        face_result = await self.providers.match_face(
            registration.participant_id, face_payload, face_template
        )
        if not face_result.accepted:
            raise ValueError(face_result.message or "Face verification failed at entry gate")

        registration.status = VerificationStatus.CHECKED_IN
        registration.checked_in_at = datetime.now(UTC)
        registration.updated_at = datetime.now(UTC)
        await self._commit(registration)
        return registration

    async def _commit(self, registration: Registration):
        session = await self._get_session()
        session.add(registration)
        await session.commit()
        await session.refresh(registration)

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None
