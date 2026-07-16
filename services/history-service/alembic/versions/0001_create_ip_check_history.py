"""Create IP check history.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_check_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("ip_address", sa.String(length=39), nullable=False),
        sa.Column("ip_version", sa.SmallInteger(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("is_whitelisted", sa.Boolean(), nullable=True),
        sa.Column("abuse_confidence_score", sa.SmallInteger(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("usage_type", sa.String(length=100), nullable=True),
        sa.Column("isp", sa.String(length=255), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("total_reports", sa.Integer(), nullable=False),
        sa.Column("num_distinct_users", sa.Integer(), nullable=False),
        sa.Column("last_reported_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("max_age_days", sa.SmallInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("checked_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint(
            "abuse_confidence_score BETWEEN 0 AND 100",
            name="ck_ip_check_history_score",
        ),
        sa.CheckConstraint("ip_version IN (4, 6)", name="ck_ip_check_history_version"),
        sa.CheckConstraint("is_public = 1", name="ck_ip_check_history_public"),
        sa.CheckConstraint(
            "max_age_days BETWEEN 1 AND 365", name="ck_ip_check_history_max_age"
        ),
        sa.CheckConstraint(
            "num_distinct_users >= 0", name="ck_ip_check_history_distinct_users"
        ),
        sa.CheckConstraint("total_reports >= 0", name="ck_ip_check_history_reports"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
        mariadb_charset="utf8mb4",
        mariadb_engine="InnoDB",
    )
    op.create_index(
        "ix_ip_check_history_ip_address",
        "ip_check_history",
        ["ip_address"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ip_check_history_ip_address", table_name="ip_check_history")
    op.drop_table("ip_check_history")
