"""Allow external OTP providers to avoid storing one-time codes.

Revision ID: 0002_nullable_otp_code
Revises: 0001_initial
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002_nullable_otp_code"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("registrations") as batch_op:
        batch_op.alter_column("otp_code", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("registrations") as batch_op:
        batch_op.alter_column("otp_code", nullable=False)