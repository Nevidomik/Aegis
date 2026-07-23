"""Add persisted blacklist snapshot change metrics.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blacklist_snapshots",
        sa.Column("added_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "blacklist_snapshots",
        sa.Column("removed_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "blacklist_snapshots",
        sa.Column("turnover_percent", sa.Numeric(7, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_blacklist_snapshots_added_count",
        "blacklist_snapshots",
        "added_count IS NULL OR added_count >= 0",
    )
    op.create_check_constraint(
        "ck_blacklist_snapshots_removed_count",
        "blacklist_snapshots",
        "removed_count IS NULL OR removed_count >= 0",
    )
    op.create_check_constraint(
        "ck_blacklist_snapshots_turnover",
        "blacklist_snapshots",
        "turnover_percent IS NULL OR turnover_percent BETWEEN 0 AND 100",
    )
    op.create_index(
        "ix_blacklist_snapshots_change_baseline",
        "blacklist_snapshots",
        ["provider", "confidence_minimum", "requested_limit", "snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_blacklist_snapshots_change_baseline",
        table_name="blacklist_snapshots",
    )
    op.drop_constraint(
        "ck_blacklist_snapshots_turnover",
        "blacklist_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_blacklist_snapshots_removed_count",
        "blacklist_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_blacklist_snapshots_added_count",
        "blacklist_snapshots",
        type_="check",
    )
    op.drop_column("blacklist_snapshots", "turnover_percent")
    op.drop_column("blacklist_snapshots", "removed_count")
    op.drop_column("blacklist_snapshots", "added_count")
