from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    venue: Mapped[str] = mapped_column(Text, default="", nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    registration_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    participant_types: Mapped[str] = mapped_column(Text, default="Attendee,Speaker,VIP,Organizer,Delegate", nullable=False)
    verification_requirements: Mapped[str] = mapped_column(
        Text, default="otp,face,liveness,pad", nullable=False
    )
    status: Mapped[str] = mapped_column(Text, default="published", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    registrations: Mapped[list[Registration]] = relationship(
        "Registration",
        back_populates="event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    mobile: Mapped[str] = mapped_column(Text, nullable=False)
    participant_type: Mapped[str] = mapped_column(Text, default="Attendee", nullable=False)
    organization: Mapped[str] = mapped_column(Text, default="Individual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    registrations: Mapped[list[Registration]] = relationship(
        "Registration",
        back_populates="participant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    biometrics: Mapped[list[BiometricVerification]] = relationship(
        "BiometricVerification",
        back_populates="participant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_salt: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, default="admin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class BiometricVerification(Base):
    __tablename__ = "biometric_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    verification_id: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider_reference: Mapped[str] = mapped_column(Text, nullable=False)
    face_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    liveness_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pad_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    iris_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fingerprint_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_id: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    face_embedding: Mapped[str | None] = mapped_column(Text, nullable=True)

    participant: Mapped[Participant] = relationship(
        "Participant",
        back_populates="biometrics",
        lazy="selectin",
    )

    @property
    def liveness_passed(self) -> bool:
        return self.liveness_verified

    @liveness_passed.setter
    def liveness_passed(self, value: bool) -> None:
        self.liveness_verified = value

    @property
    def verification_date(self) -> datetime:
        return self.verified_at

    @verification_date.setter
    def verification_date(self, value: datetime) -> None:
        self.verified_at = value


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.event_id", ondelete="CASCADE"), index=True, nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id", ondelete="CASCADE"), index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    mobile: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="otp_pending", nullable=False)
    otp_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_secret: Mapped[str] = mapped_column(Text, nullable=False)
    otp_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    face_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    liveness_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pad_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qr_token: Mapped[str | None] = mapped_column(Text, unique=True, index=True, nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    face_match: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped[Event] = relationship(
        "Event",
        back_populates="registrations",
        lazy="selectin",
    )
    participant: Mapped[Participant] = relationship(
        "Participant",
        back_populates="registrations",
        lazy="selectin",
    )

    @property
    def qr_code(self) -> str | None:
        return self.qr_token

    @qr_code.setter
    def qr_code(self, value: str | None) -> None:
        self.qr_token = value


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_username: Mapped[str] = mapped_column(Text, default="system", nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class CheckInRecord(Base):
    __tablename__ = "check_ins"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    participant_id: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    gate: Mapped[str] = mapped_column(Text, default="main", nullable=False)
    operator: Mapped[str] = mapped_column(Text, default="admin", nullable=False)
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


def create_db_engine():
    return create_async_engine(settings.database_url, echo=settings.database_echo, future=True)


def create_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def upgrade_legacy_sqlite_schema(connection: Connection) -> None:
    if connection.dialect.name != "sqlite":
        return

    additions = {
        "events": {
            "venue": "TEXT NOT NULL DEFAULT ''",
            "registration_start": "DATETIME",
            "registration_end": "DATETIME",
            "participant_types": (
                "TEXT NOT NULL DEFAULT 'Attendee,Speaker,VIP,Organizer,Delegate'"
            ),
            "verification_requirements": "TEXT NOT NULL DEFAULT 'otp,face,liveness,pad'",
            "status": "TEXT NOT NULL DEFAULT 'published'",
        },
        "biometric_verifications": {
            "face_embedding": "TEXT",
        },
    }
    schema = inspect(connection)
    existing_tables = set(schema.get_table_names())
    for table_name, columns in additions.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in schema.get_columns(table_name)}
        for column_name, definition in columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f'ALTER TABLE "{table_name}" ADD COLUMN '
                        f'"{column_name}" {definition}'
                    )
                )


@event.listens_for(Registration.__table__, "before_create")
def _create_indexes(target, connection, **kwargs):
    pass
