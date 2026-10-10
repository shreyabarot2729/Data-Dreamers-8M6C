"""Store participant postal addresses separately.

Revision ID: 0004_participant_addresses
Revises: 0003_local_face_template
Create Date: 2026-10-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_participant_addresses"
down_revision: str | None = "0003_local_face_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "participant_addresses" not in inspector.get_table_names():
        op.create_table(
            "participant_addresses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "participant_id",
                sa.Text(),
                sa.ForeignKey("participants.participant_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("address_line1", sa.Text(), nullable=False),
            sa.Column("address_line2", sa.Text(), nullable=True),
            sa.Column("city", sa.Text(), nullable=False),
            sa.Column("state_province", sa.Text(), nullable=False),
            sa.Column("country", sa.Text(), nullable=False),
            sa.Column("postal_code", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    address_indexes = {
        index["name"]: index for index in inspector.get_indexes("participant_addresses")
    }
    index_name = "ix_participant_addresses_participant_id"
    if index_name in address_indexes and not address_indexes[index_name]["unique"]:
        op.drop_index(index_name, table_name="participant_addresses")
        address_indexes.pop(index_name)
    if index_name not in address_indexes:
        op.create_index(
            index_name,
            "participant_addresses",
            ["participant_id"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_participant_addresses_participant_id",
        table_name="participant_addresses",
    )
    op.drop_table("participant_addresses")
