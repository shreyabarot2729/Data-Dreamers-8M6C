"""Initial schema: events, participants, biometric_verifications, registrations

Revision ID: 0001_initial
Revises: 
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Events
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_event_id", "events", ["event_id"])

    # 2. Participants
    op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("participant_id", sa.Text(), nullable=False, unique=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("participant_type", sa.Text(), nullable=False, server_default="Attendee"),
        sa.Column("organization", sa.Text(), nullable=False, server_default="Individual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_participants_participant_id", "participants", ["participant_id"])
    op.create_index("ix_participants_email", "participants", ["email"])

    # 3. Biometric Verifications
    op.create_table(
        "biometric_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("verification_id", sa.Text(), nullable=False, unique=True),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participants.participant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_reference", sa.Text(), nullable=False),
        sa.Column("face_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("liveness_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("pad_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("iris_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("fingerprint_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("consent_id", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bio_verification_id", "biometric_verifications", ["verification_id"])
    op.create_index("ix_bio_participant_id", "biometric_verifications", ["participant_id"])
    op.create_index("ix_bio_consent_id", "biometric_verifications", ["consent_id"])

    # 4. Registrations
    op.create_table(
        "registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registration_id", sa.Text(), nullable=False, unique=True),
        sa.Column("event_id", sa.Text(), sa.ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False),
        sa.Column("participant_id", sa.Text(), sa.ForeignKey("participants.participant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="otp_pending"),
        sa.Column("otp_code", sa.Text(), nullable=False),
        sa.Column("otp_secret", sa.Text(), nullable=False),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("face_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("liveness_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("pad_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("qr_token", sa.Text(), nullable=True, unique=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("face_match", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reg_event_id", "registrations", ["event_id"])
    op.create_index("ix_reg_participant_id", "registrations", ["participant_id"])
    op.create_index("ix_reg_email", "registrations", ["email"])
    op.create_index("ix_reg_status", "registrations", ["status"])


def downgrade() -> None:
    op.drop_table("registrations")
    op.drop_table("biometric_verifications")
    op.drop_table("participants")
    op.drop_table("events")
