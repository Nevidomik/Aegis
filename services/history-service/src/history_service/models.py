"""SQLAlchemy ORM models owned by the History service."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
