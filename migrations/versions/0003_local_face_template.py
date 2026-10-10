"""Store local face embeddings for opted-in participants.

Revision ID: 0003_local_face_template
Revises: 0002_nullable_otp_code
Create Date: 2026-10-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_local_face_template"
down_revision: str | None = "0002_nullable_otp_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("face_template", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "face_template")
