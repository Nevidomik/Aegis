"""Create blacklist snapshot persistence.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blacklist_snapshots",
        sa.Column("snapshot_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_generated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("fetched_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("confidence_minimum", sa.SmallInteger(), nullable=False),
        sa.Column("requested_limit", sa.SmallInteger(), nullable=False),
        sa.Column("returned_count", sa.SmallInteger(), nullable=False),
        sa.Column("rate_limit_limit", sa.Integer(), nullable=True),
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=True),
        sa.Column("rate_limit_reset_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "confidence_minimum BETWEEN 0 AND 100",
            name="ck_blacklist_snapshots_confidence",
        ),
        sa.CheckConstraint(
            "requested_limit BETWEEN 1 AND 1000",
            name="ck_blacklist_snapshots_requested_limit",
        ),
        sa.CheckConstraint(
            "returned_count BETWEEN 0 AND 1000",
            name="ck_blacklist_snapshots_returned_count",
        ),
        sa.CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_limit >= 0",
            name="ck_blacklist_snapshots_rate_limit",
        ),
        sa.CheckConstraint(
            "rate_limit_remaining IS NULL OR rate_limit_remaining >= 0",
            name="ck_blacklist_snapshots_rate_remaining",
        ),
        sa.CheckConstraint(
            "retry_after_seconds IS NULL OR retry_after_seconds >= 0",
            name="ck_blacklist_snapshots_retry_after",
        ),
        sa.CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_remaining IS NULL "
            "OR rate_limit_remaining <= rate_limit_limit",
            name="ck_blacklist_snapshots_rate_consistency",
        ),
        sa.PrimaryKeyConstraint("snapshot_id"),
        mariadb_charset="utf8mb4",
        mariadb_engine="InnoDB",
    )
    op.create_index(
        "uq_blacklist_snapshots_provider_generated",
        "blacklist_snapshots",
        ["provider", "provider_generated_at"],
        unique=True,
    )

    op.create_table(
        "blacklist_snapshot_entries",
        sa.Column("entry_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("ip_address", sa.String(length=39), nullable=False),
        sa.Column("ip_version", sa.SmallInteger(), nullable=False),
        sa.Column("abuse_confidence_score", sa.SmallInteger(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("last_reported_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.CheckConstraint(
            "ip_version IN (4, 6)", name="ck_blacklist_entries_ip_version"
        ),
        sa.CheckConstraint(
            "abuse_confidence_score BETWEEN 0 AND 100",
            name="ck_blacklist_entries_score",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["blacklist_snapshots.snapshot_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entry_id"),
        mariadb_charset="utf8mb4",
        mariadb_engine="InnoDB",
    )
    op.create_index(
        "uq_blacklist_entries_snapshot_ip",
        "blacklist_snapshot_entries",
        ["snapshot_id", "ip_address"],
        unique=True,
    )
    op.create_index(
        "ix_blacklist_entries_page",
        "blacklist_snapshot_entries",
        [
            "snapshot_id",
            sa.text("abuse_confidence_score DESC"),
            sa.text("last_reported_at DESC"),
            "ip_address",
        ],
        unique=False,
    )

    op.create_table(
        "blacklist_sync_runs",
        sa.Column("sync_run_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("confidence_minimum", sa.SmallInteger(), nullable=False),
        sa.Column("requested_limit", sa.SmallInteger(), nullable=False),
        sa.Column("provider_http_status", sa.SmallInteger(), nullable=True),
        sa.Column("rate_limit_limit", sa.Integer(), nullable=True),
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=True),
        sa.Column("rate_limit_reset_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'duplicate', 'rate_limited', 'failed')",
            name="ck_blacklist_sync_runs_status",
        ),
        sa.CheckConstraint(
            "confidence_minimum BETWEEN 0 AND 100",
            name="ck_blacklist_sync_runs_confidence",
        ),
        sa.CheckConstraint(
            "requested_limit BETWEEN 1 AND 1000",
            name="ck_blacklist_sync_runs_requested_limit",
        ),
        sa.CheckConstraint(
            "provider_http_status IS NULL OR provider_http_status BETWEEN 100 AND 599",
            name="ck_blacklist_sync_runs_http_status",
        ),
        sa.CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_limit >= 0",
            name="ck_blacklist_sync_runs_rate_limit",
        ),
        sa.CheckConstraint(
            "rate_limit_remaining IS NULL OR rate_limit_remaining >= 0",
            name="ck_blacklist_sync_runs_rate_remaining",
        ),
        sa.CheckConstraint(
            "retry_after_seconds IS NULL OR retry_after_seconds >= 0",
            name="ck_blacklist_sync_runs_retry_after",
        ),
        sa.CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_remaining IS NULL "
            "OR rate_limit_remaining <= rate_limit_limit",
            name="ck_blacklist_sync_runs_rate_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["blacklist_snapshots.snapshot_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("sync_run_id"),
        sa.UniqueConstraint("request_id"),
        mariadb_charset="utf8mb4",
        mariadb_engine="InnoDB",
    )
    op.create_index(
        "ix_blacklist_sync_runs_snapshot",
        "blacklist_sync_runs",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_blacklist_sync_runs_status_next",
        "blacklist_sync_runs",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("blacklist_sync_runs")
    op.drop_table("blacklist_snapshot_entries")
    op.drop_table("blacklist_snapshots")
