"""Add blacklist synchronization scheduling reason.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blacklist_sync_runs",
        sa.Column("next_attempt_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blacklist_sync_runs", "next_attempt_reason")
