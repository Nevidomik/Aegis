"""SQLAlchemy ORM models owned by the History service."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for History ORM models."""


class IpCheckHistory(Base):
    """One successfully normalized IP reputation lookup."""

    __tablename__ = "ip_check_history"
    __table_args__ = (
        CheckConstraint("ip_version IN (4, 6)", name="ck_ip_check_history_version"),
        CheckConstraint("is_public = 1", name="ck_ip_check_history_public"),
        CheckConstraint(
            "abuse_confidence_score BETWEEN 0 AND 100",
            name="ck_ip_check_history_score",
        ),
        CheckConstraint("total_reports >= 0", name="ck_ip_check_history_reports"),
        CheckConstraint(
            "num_distinct_users >= 0", name="ck_ip_check_history_distinct_users"
        ),
        CheckConstraint(
            "max_age_days BETWEEN 1 AND 365", name="ck_ip_check_history_max_age"
        ),
        Index("ix_ip_check_history_ip_address", "ip_address"),
        {"mariadb_engine": "InnoDB", "mariadb_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(39), nullable=False)
    ip_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_whitelisted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    abuse_confidence_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    usage_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    isp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_reports: Mapped[int] = mapped_column(Integer, nullable=False)
    num_distinct_users: Mapped[int] = mapped_column(Integer, nullable=False)
    last_reported_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )
    max_age_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class BlacklistSnapshot(Base):
    """One complete accepted provider blacklist snapshot."""

    __tablename__ = "blacklist_snapshots"
    __table_args__ = (
        CheckConstraint(
            "confidence_minimum BETWEEN 0 AND 100",
            name="ck_blacklist_snapshots_confidence",
        ),
        CheckConstraint(
            "requested_limit BETWEEN 1 AND 1000",
            name="ck_blacklist_snapshots_requested_limit",
        ),
        CheckConstraint(
            "returned_count BETWEEN 0 AND 1000",
            name="ck_blacklist_snapshots_returned_count",
        ),
        CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_limit >= 0",
            name="ck_blacklist_snapshots_rate_limit",
        ),
        CheckConstraint(
            "rate_limit_remaining IS NULL OR rate_limit_remaining >= 0",
            name="ck_blacklist_snapshots_rate_remaining",
        ),
        CheckConstraint(
            "retry_after_seconds IS NULL OR retry_after_seconds >= 0",
            name="ck_blacklist_snapshots_retry_after",
        ),
        CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_remaining IS NULL "
            "OR rate_limit_remaining <= rate_limit_limit",
            name="ck_blacklist_snapshots_rate_consistency",
        ),
        {"mariadb_engine": "InnoDB", "mariadb_charset": "utf8mb4"},
    )

    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_generated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    confidence_minimum: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    requested_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    returned_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rate_limit_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_reset_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entries: Mapped[list[BlacklistSnapshotEntry]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sync_runs: Mapped[list[BlacklistSyncRun]] = relationship(
        back_populates="snapshot",
        passive_deletes=True,
    )


class BlacklistSnapshotEntry(Base):
    """One normalized address belonging to a blacklist snapshot."""

    __tablename__ = "blacklist_snapshot_entries"
    __table_args__ = (
        CheckConstraint("ip_version IN (4, 6)", name="ck_blacklist_entries_ip_version"),
        CheckConstraint(
            "abuse_confidence_score BETWEEN 0 AND 100",
            name="ck_blacklist_entries_score",
        ),
        {"mariadb_engine": "InnoDB", "mariadb_charset": "utf8mb4"},
    )

    entry_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blacklist_snapshots.snapshot_id", ondelete="CASCADE"),
        nullable=False,
    )
    ip_address: Mapped[str] = mapped_column(String(39), nullable=False)
    ip_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    abuse_confidence_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    last_reported_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )

    snapshot: Mapped[BlacklistSnapshot] = relationship(back_populates="entries")


Index(
    "uq_blacklist_snapshots_provider_generated",
    BlacklistSnapshot.provider,
    BlacklistSnapshot.provider_generated_at,
    unique=True,
)
Index(
    "uq_blacklist_entries_snapshot_ip",
    BlacklistSnapshotEntry.snapshot_id,
    BlacklistSnapshotEntry.ip_address,
    unique=True,
)
Index(
    "ix_blacklist_entries_page",
    BlacklistSnapshotEntry.snapshot_id,
    BlacklistSnapshotEntry.abuse_confidence_score.desc(),
    BlacklistSnapshotEntry.last_reported_at.desc(),
    BlacklistSnapshotEntry.ip_address,
)


class BlacklistSyncRun(Base):
    """One blacklist synchronization attempt and its safe outcome metadata."""

    __tablename__ = "blacklist_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'duplicate', 'rate_limited', 'failed')",
            name="ck_blacklist_sync_runs_status",
        ),
        CheckConstraint(
            "confidence_minimum BETWEEN 0 AND 100",
            name="ck_blacklist_sync_runs_confidence",
        ),
        CheckConstraint(
            "requested_limit BETWEEN 1 AND 1000",
            name="ck_blacklist_sync_runs_requested_limit",
        ),
        CheckConstraint(
            "provider_http_status IS NULL OR provider_http_status BETWEEN 100 AND 599",
            name="ck_blacklist_sync_runs_http_status",
        ),
        CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_limit >= 0",
            name="ck_blacklist_sync_runs_rate_limit",
        ),
        CheckConstraint(
            "rate_limit_remaining IS NULL OR rate_limit_remaining >= 0",
            name="ck_blacklist_sync_runs_rate_remaining",
        ),
        CheckConstraint(
            "retry_after_seconds IS NULL OR retry_after_seconds >= 0",
            name="ck_blacklist_sync_runs_retry_after",
        ),
        CheckConstraint(
            "rate_limit_limit IS NULL OR rate_limit_remaining IS NULL "
            "OR rate_limit_remaining <= rate_limit_limit",
            name="ck_blacklist_sync_runs_rate_consistency",
        ),
        Index("ix_blacklist_sync_runs_status_next", "status", "next_attempt_at"),
        Index("ix_blacklist_sync_runs_snapshot", "snapshot_id"),
        {"mariadb_engine": "InnoDB", "mariadb_charset": "utf8mb4"},
    )

    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("blacklist_snapshots.snapshot_id", ondelete="SET NULL"),
        nullable=True,
    )
    confidence_minimum: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    requested_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    provider_http_status: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
    )
    rate_limit_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_reset_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )
    next_attempt_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    snapshot: Mapped[BlacklistSnapshot | None] = relationship(
        back_populates="sync_runs"
    )
