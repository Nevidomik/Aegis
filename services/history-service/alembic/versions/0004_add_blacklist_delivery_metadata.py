"""Add Provider delivery identity and receipt timestamp.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blacklist_snapshots",
        sa.Column("delivery_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "blacklist_snapshots",
        sa.Column("received_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.create_unique_constraint(
        "uq_blacklist_snapshots_delivery_id",
        "blacklist_snapshots",
        ["delivery_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_blacklist_snapshots_delivery_id",
        "blacklist_snapshots",
        type_="unique",
    )
    op.drop_column("blacklist_snapshots", "received_at")
    op.drop_column("blacklist_snapshots", "delivery_id")
