from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import (
    AdminUser,
    AuditLog,
    BiometricVerification,
    CheckInRecord,
    Event,
    Participant,
    Registration,
)
from app.providers import (
    VerificationProviderFactory,
    generate_consent_id,
    generate_otp,
    generate_participant_id,
    generate_provider_reference,
    generate_registration_id,
    generate_verification_id,
)
from app.schemas import CreateEventRequest, CreateRegistrationRequest, UpdateEventRequest


class VerificationStatus(StrEnum):
    OTP_PENDING = "otp_pending"
    FACE_PENDING = "face_pending"
    LIVENESS_PENDING = "liveness_pending"
    PAD_PENDING = "pad_pending"
    REGISTERED = "registered"
    CHECKED_IN = "checked_in"
    REJECTED = "rejected"
    WAITLIST = "waitlist"
    CANCELLED = "cancelled"


@dataclass
class RegistrationService:
    session_factory: async_sessionmaker
    providers: VerificationProviderFactory | None = None

    def __post_init__(self):
        self.session: AsyncSession | None = None
        if self.providers is None:
            self.providers = VerificationProviderFactory()

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = self.session_factory()
        return self.session

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        ).hex()

    @staticmethod
    def _verify_password(password: str, password_hash: str, salt: str) -> bool:
        return RegistrationService._hash_password(password, salt) == password_hash

    @staticmethod
    def _build_admin_token(admin: AdminUser) -> str:
        payload = (
            f"{admin.id}:{admin.email}:{admin.username}:{admin.role}:"
            f"{admin.last_login_at.isoformat() if admin.last_login_at else admin.created_at.isoformat()}"
        )
        signature = hmac.new(settings.secret_key.encode("utf-8"), payload.encode(), hashlib.sha256).hexdigest()
        encoded = base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("utf-8")
        return encoded

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

    async def seed_default_admin(self) -> AdminUser:
        session = await self._get_session()
        existing = await session.execute(
            select(AdminUser).where(
                or_(AdminUser.email == settings.admin_email, AdminUser.username == settings.admin_username)
            )
        )
        admin = existing.scalar_one_or_none()
        if admin is not None:
            return admin

        if not settings.admin_password:
            raise ValueError("Set ADMIN_PASSWORD before initializing the default admin account")

        salt = secrets.token_hex(8)
        admin = AdminUser(
            username=settings.admin_username,
            email=settings.admin_email,
            password_hash=self._hash_password(settings.admin_password, salt),
            password_salt=salt,
            role=settings.admin_role,
            is_active=True,
            mfa_enabled=False,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin

    async def authenticate_admin(
        self,
        identifier: str,
        password: str,
        mfa_code: str | None = None,
    ) -> AdminUser:
        session = await self._get_session()
        result = await session.execute(
            select(AdminUser).where(
                or_(AdminUser.email == identifier.lower(), AdminUser.username == identifier)
            )
        )
        admin = result.scalar_one_or_none()
        if admin is None:
            raise ValueError("Invalid admin credentials")
        if not admin.is_active:
            raise ValueError("This admin account is disabled")
        if not self._verify_password(password, admin.password_hash, admin.password_salt):
            raise ValueError("Invalid admin credentials")
        if settings.admin_mfa_required or admin.mfa_enabled:
            if not mfa_code:
                raise ValueError("MFA code required")
            raise ValueError("MFA verification is not configured for this system")
        admin.last_login_at = datetime.now(UTC)
        await session.commit()
        return admin

    async def validate_admin_token(self, token: str) -> AdminUser:
        try:
            decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            raise ValueError("Invalid admin token") from exc

        payload, signature = decoded.rsplit(":", 1)
        expected = hmac.new(settings.secret_key.encode("utf-8"), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid admin token")

        admin_id = int(payload.split(":", 1)[0])
        session = await self._get_session()
        result = await session.execute(select(AdminUser).where(AdminUser.id == admin_id))
        admin = result.scalar_one_or_none()
        if admin is None or not admin.is_active:
            raise ValueError("Admin account not found or inactive")
        return admin

    async def get_admin_dashboard(self) -> dict:
        session = await self._get_session()
        total_events = await session.scalar(select(func.count(Event.id)))
        total_participants = await session.scalar(select(func.count(Participant.id)))
        total_registrations = await session.scalar(select(func.count(Registration.id)))
        pending_otp_verification = await session.scalar(
            select(func.count(Registration.id)).where(Registration.status == "otp_pending")
        )
        pending_biometric_verification = await session.scalar(
            select(func.count(Registration.id)).where(
                Registration.status.in_({"face_pending", "liveness_pending", "pad_pending"})
            )
        )
        verified_participants = await session.scalar(
            select(func.count(Registration.id)).where(
                Registration.status.in_({"registered", "checked_in"})
            )
        )
        qr_passes_issued = await session.scalar(
            select(func.count(Registration.id)).where(Registration.qr_token.is_not(None))
        )
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today_checkins = await session.scalar(
            select(func.count(Registration.id)).where(
                Registration.checked_in_at >= today,
                Registration.status == "checked_in",
            )
        )
        failed_verification_attempts = await session.scalar(
            select(func.count(Registration.id)).where(
                Registration.status == "rejected"
            )
        )
        recent_registrations = await session.execute(
            select(Registration).order_by(Registration.created_at.desc()).limit(5)
        )
        recent_activity = [
            f"{item.first_name} {item.last_name} registered for {item.event_id}"
            for item in recent_registrations.scalars().all()
        ]

        return {
            "total_events": total_events or 0,
            "total_participants": total_participants or 0,
            "total_registrations": total_registrations or 0,
            "pending_otp_verification": pending_otp_verification or 0,
            "pending_biometric_verification": pending_biometric_verification or 0,
            "verified_participants": verified_participants or 0,
            "qr_passes_issued": qr_passes_issued or 0,
            "today_checkins": today_checkins or 0,
            "failed_verification_attempts": failed_verification_attempts or 0,
            "recent_activity": recent_activity,
        }

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
                    "venue": getattr(ev, "venue", "") or "",
                    "capacity": ev.capacity,
                    "registration_start": getattr(ev, "registration_start", None),
                    "registration_end": getattr(ev, "registration_end", None),
                    "participant_types": getattr(ev, "participant_types", "Attendee,Speaker,VIP,Organizer,Delegate"),
                    "verification_requirements": getattr(ev, "verification_requirements", "otp,face,liveness,pad"),
                    "status": getattr(ev, "status", "published"),
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
            venue=request.venue,
            capacity=request.capacity,
            registration_start=request.registration_start,
            registration_end=request.registration_end,
            participant_types=request.participant_types,
            verification_requirements=request.verification_requirements,
            status=request.status,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    async def get_event_by_code(self, event_id: str) -> Event:
        session = await self._get_session()
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if event is None:
            raise ValueError("Event not found")
        return event

    async def update_event(self, event_id: str, request: UpdateEventRequest) -> Event:
        event = await self.get_event_by_code(event_id)
        session = await self._get_session()
        if request.event_name is not None:
            event.event_name = request.event_name
        if request.event_date is not None:
            event.event_date = request.event_date
        if request.venue is not None:
            event.venue = request.venue
        if request.capacity is not None:
            event.capacity = request.capacity
        if request.registration_start is not None:
            event.registration_start = request.registration_start
        if request.registration_end is not None:
            event.registration_end = request.registration_end
        if request.participant_types is not None:
            event.participant_types = request.participant_types
        if request.verification_requirements is not None:
            event.verification_requirements = request.verification_requirements
        if request.status is not None:
            event.status = request.status
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    async def log_audit(
        self,
        admin: AdminUser | None,
        action: str,
        entity_type: str,
        entity_id: str,
        details: str = "",
    ) -> None:
        session = await self._get_session()
        entry = AuditLog(
            admin_id=admin.id if admin else None,
            admin_username=admin.username if admin else "system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
        session.add(entry)
        await session.commit()

    async def get_audit_logs(self, limit: int = 100) -> list[AuditLog]:
        session = await self._get_session()
        result = await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get_participant_by_key(self, key: str) -> Participant:
        session = await self._get_session()
        if key.isdigit():
            participant = await session.get(Participant, int(key))
            if participant is not None:
                return participant
        result = await session.execute(
            select(Participant).where(Participant.participant_id == key)
        )
        participant = result.scalar_one_or_none()
        if participant is None:
            raise ValueError("Participant not found")
        return participant

    async def search_participants(self, query: str | None = None) -> list[Participant]:
        session = await self._get_session()
        stmt = select(Participant).order_by(Participant.id.desc())
        if query:
            term = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Participant.participant_id.ilike(term),
                    Participant.full_name.ilike(term),
                    Participant.email.ilike(term),
                    Participant.mobile.ilike(term),
                )
            )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def filter_registrations(
        self,
        event_id: str | None = None,
        status: str | None = None,
        search: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[Registration]:
        session = await self._get_session()
        stmt = select(Registration).order_by(Registration.id.desc())
        if event_id:
            stmt = stmt.where(Registration.event_id == event_id)
        if status:
            stmt = stmt.where(Registration.status == status)
        if created_from:
            stmt = stmt.where(Registration.created_at >= created_from)
        if created_to:
            stmt = stmt.where(Registration.created_at < created_to)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Registration.registration_id.ilike(term),
                    Registration.email.ilike(term),
                    Registration.participant_id.ilike(term),
                    Registration.first_name.ilike(term),
                    Registration.last_name.ilike(term),
                )
            )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_registration_status(
        self,
        registration_id: int,
        status: str,
        reason: str = "",
    ) -> Registration:
        registration = await self._load_registration(registration_id)
        allowed = {
            VerificationStatus.REGISTERED,
            VerificationStatus.REJECTED,
            VerificationStatus.WAITLIST,
            VerificationStatus.CANCELLED,
            VerificationStatus.OTP_PENDING,
            VerificationStatus.FACE_PENDING,
            VerificationStatus.LIVENESS_PENDING,
            VerificationStatus.PAD_PENDING,
        }
        if status not in {item.value for item in allowed}:
            raise ValueError(f"Unsupported registration status: {status}")

        if status == VerificationStatus.REGISTERED:
            if not all(
                [
                    registration.face_verified,
                    registration.liveness_verified,
                    registration.pad_verified,
                ]
            ):
                raise ValueError("Registration cannot be approved until biometric verification passes")
            if registration.status not in {
                VerificationStatus.REGISTERED,
                VerificationStatus.CHECKED_IN,
            }:
                event = await self.get_event_by_code(registration.event_id)
                if event.status != "published":
                    raise ValueError("Registration cannot be approved for an unpublished event")
                session = await self._get_session()
                active_count = await session.scalar(
                    select(func.count(Registration.id)).where(
                        Registration.event_id == registration.event_id,
                        Registration.status.in_(
                            {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}
                        ),
                        Registration.id != registration.id,
                    )
                )
                if (active_count or 0) >= event.capacity:
                    raise ValueError("Event capacity has been reached")
                duplicate = await session.scalar(
                    select(Registration.id).where(
                        Registration.event_id == registration.event_id,
                        Registration.participant_id == registration.participant_id,
                        Registration.status.in_(
                            {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}
                        ),
                        Registration.id != registration.id,
                    ).limit(1)
                )
                if duplicate is not None:
                    raise ValueError("Participant already has an active registration for this event")

        registration.status = status
        registration.updated_at = datetime.now(UTC)
        if status == VerificationStatus.REGISTERED and registration.qr_token is None:
            if all([
                registration.face_verified,
                registration.liveness_verified,
                registration.pad_verified,
            ]):
                registration.registered_at = datetime.now(UTC)
                registration.qr_token = f"event-registration:{secrets.token_urlsafe(32)}"
        if status in {VerificationStatus.REJECTED, VerificationStatus.CANCELLED}:
            registration.qr_token = None
        if reason:
            registration.face_match = (registration.face_match or "") + f" | admin: {reason}"
        await self._commit(registration)
        return registration

    async def revoke_qr_pass(self, registration_id: int, reason: str = "") -> Registration:
        registration = await self._load_registration(registration_id)
        registration.qr_token = None
        registration.updated_at = datetime.now(UTC)
        if reason:
            registration.face_match = (registration.face_match or "") + f" | revoke: {reason}"
        await self._commit(registration)
        return registration

    async def reissue_qr_pass(self, registration_id: int) -> Registration:
        registration = await self._load_registration(registration_id)
        if registration.status not in {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}:
            raise ValueError("QR pass can only be reissued for registered participants")
        if not all(
            [
                registration.face_verified,
                registration.liveness_verified,
                registration.pad_verified,
            ]
        ):
            raise ValueError("QR pass cannot be issued without completed biometric verification")
        registration.qr_token = f"event-registration:{secrets.token_urlsafe(32)}"
        registration.updated_at = datetime.now(UTC)
        await self._commit(registration)
        return registration

    async def review_biometric(
        self,
        verification_id: str,
        decision: str,
        reason: str = "",
        registration_id: int | None = None,
    ) -> BiometricVerification:
        session = await self._get_session()
        result = await session.execute(
            select(BiometricVerification).where(BiometricVerification.verification_id == verification_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise ValueError("Biometric verification not found")

        decision_norm = decision.lower()
        approved = decision_norm in {"approve", "approved", "pass", "passed"}
        rejected = decision_norm in {"reject", "rejected", "fail", "failed"}
        if not approved and not rejected:
            raise ValueError("Decision must be approve or reject")

        registration = None
        if registration_id is not None:
            registration = await self._load_registration(registration_id)
            if registration.participant_id != record.participant_id:
                raise ValueError("Registration does not belong to this biometric participant")

        if approved:
            record.face_verified = True
            record.liveness_verified = True
            record.pad_verified = True
        else:
            record.face_verified = False
            record.liveness_verified = False
            record.pad_verified = False

        if reason:
            record.provider_reference = f"{record.provider_reference} | review: {reason}"

        if registration is not None:
            if approved:
                registration.face_verified = True
                registration.liveness_verified = True
                registration.pad_verified = True
                registration.status = VerificationStatus.REGISTERED
                if registration.qr_token is None:
                    registration.registered_at = datetime.now(UTC)
                    registration.qr_token = f"event-registration:{secrets.token_urlsafe(32)}"
            else:
                registration.status = VerificationStatus.REJECTED
            registration.updated_at = datetime.now(UTC)
            await self._commit(registration)

        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    async def list_qr_passes(self, search: str | None = None) -> list[dict]:
        registrations = await self.filter_registrations(search=search)
        rows = []
        for reg in registrations:
            if reg.qr_token is None and reg.status not in {
                VerificationStatus.REGISTERED,
                VerificationStatus.CHECKED_IN,
            }:
                continue
            rows.append(
                {
                    "registration_id": reg.id,
                    "registration_code": reg.registration_id,
                    "participant_id": reg.participant_id,
                    "event_id": reg.event_id,
                    "full_name": f"{reg.first_name} {reg.last_name}".strip(),
                    "status": reg.status,
                    "qr_token": reg.qr_token,
                    "revoked": reg.qr_token is None,
                    "registered_at": reg.registered_at,
                    "checked_in_at": reg.checked_in_at,
                }
            )
        return rows

    async def admin_check_in(
        self,
        admin: AdminUser,
        qr_token: str | None = None,
        registration_id: int | None = None,
        event_id: str | None = None,
        gate: str = "main",
        face_payload: str = "valid-face",
        skip_face: bool = False,
    ) -> Registration:
        if skip_face:
            session = await self._get_session()
            registration = None
            if qr_token:
                res = await session.execute(
                    select(Registration).where(Registration.qr_token == qr_token.strip())
                )
                registration = res.scalar_one_or_none()
            if registration is None and registration_id is not None:
                registration = await session.get(Registration, registration_id)
            if registration is None:
                raise ValueError("Registration not found")
            if event_id and registration.event_id != event_id:
                raise ValueError("QR pass is not valid for the selected event")
            if registration.status == VerificationStatus.CHECKED_IN:
                raise ValueError("Already checked in")
            if registration.status != VerificationStatus.REGISTERED:
                raise ValueError("Registration is not confirmed")
            if registration.qr_token is None:
                raise ValueError("QR pass has been revoked")
            registration.status = VerificationStatus.CHECKED_IN
            registration.checked_in_at = datetime.now(UTC)
            registration.updated_at = datetime.now(UTC)
            check_in = CheckInRecord(
                registration_id=registration.id,
                event_id=registration.event_id,
                participant_id=registration.participant_id,
                gate=gate,
                operator=admin.username,
            )
            session.add(check_in)
            await self._commit(registration)
            return registration

        session = await self._get_session()
        candidate = None
        if qr_token:
            result = await session.execute(
                select(Registration).where(Registration.qr_token == qr_token.strip())
            )
            candidate = result.scalar_one_or_none()
        if candidate is None and registration_id is not None:
            candidate = await session.get(Registration, registration_id)
        if candidate is not None and event_id and candidate.event_id != event_id:
            raise ValueError("QR pass is not valid for the selected event")

        registration = await self.check_in(
            registration_id=registration_id,
            face_payload=face_payload,
            qr_token=qr_token,
        )
        check_in = CheckInRecord(
            registration_id=registration.id,
            event_id=registration.event_id,
            participant_id=registration.participant_id,
            gate=gate,
            operator=admin.username,
        )
        session.add(check_in)
        await session.commit()
        return registration

    async def get_reports_summary(self) -> dict:
        session = await self._get_session()
        events = list((await session.execute(select(Event))).scalars().all())
        events_by_status: dict[str, int] = {}
        for ev in events:
            status = getattr(ev, "status", "published")
            events_by_status[status] = events_by_status.get(status, 0) + 1

        reg_rows = list((await session.execute(select(Registration.status))).all())
        registrations_by_status: dict[str, int] = {}
        for (status,) in reg_rows:
            registrations_by_status[status] = registrations_by_status.get(status, 0) + 1

        bio_total = await session.scalar(select(func.count(BiometricVerification.id))) or 0
        bio_pass = await session.scalar(
            select(func.count(BiometricVerification.id)).where(
                BiometricVerification.face_verified.is_(True),
                BiometricVerification.liveness_verified.is_(True),
                BiometricVerification.pad_verified.is_(True),
            )
        ) or 0
        pass_rate = (bio_pass / bio_total * 100) if bio_total else 0.0

        capacity_utilization = []
        for ev in events:
            reg_count = await session.scalar(
                select(func.count(Registration.id)).where(
                    Registration.event_id == ev.event_id,
                    Registration.status.in_(
                        {VerificationStatus.REGISTERED, VerificationStatus.CHECKED_IN}
                    ),
                )
            ) or 0
            utilization = (reg_count / ev.capacity * 100) if ev.capacity else 0.0
            capacity_utilization.append(
                {
                    "event_id": ev.event_id,
                    "event_name": ev.event_name,
                    "registered": reg_count,
                    "capacity": ev.capacity,
                    "utilization_percent": round(utilization, 2),
                }
            )

        return {
            "events_by_status": events_by_status,
            "registrations_by_status": registrations_by_status,
            "verification_pass_rate": round(pass_rate, 2),
            "capacity_utilization": capacity_utilization,
        }

    async def list_admin_users(self) -> list[AdminUser]:
        session = await self._get_session()
        result = await session.execute(select(AdminUser).order_by(AdminUser.id))
        return list(result.scalars().all())

    async def create_admin_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str,
    ) -> AdminUser:
        session = await self._get_session()
        normalized_username = username.strip()
        normalized_email = email.strip().lower()
        existing = await session.execute(
            select(AdminUser).where(
                or_(
                    AdminUser.username == normalized_username,
                    AdminUser.email == normalized_email,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("An admin account with that username or email already exists")

        salt = secrets.token_hex(16)
        admin = AdminUser(
            username=normalized_username,
            email=normalized_email,
            password_hash=self._hash_password(password, salt),
            password_salt=salt,
            role=role,
            is_active=True,
            mfa_enabled=False,
        )
        session.add(admin)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("An admin account with that username or email already exists") from exc
        await session.refresh(admin)
        return admin

    async def get_participants(self) -> list[Participant]:
        session = await self._get_session()
        result = await session.execute(select(Participant).order_by(Participant.id.desc()))
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
        registration.qr_token = f"event-registration:{secrets.token_urlsafe(32)}"
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

        face_result = await self.providers.match_face(registration.participant_id, face_payload)
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
