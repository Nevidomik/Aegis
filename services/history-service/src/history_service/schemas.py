"""Pydantic contracts for the internal History API."""

from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from history_service.models import IpCheckHistory


def normalize_ip(value: str) -> str:
    """Return the canonical representation of a valid IP address."""
    try:
        return str(ip_address(value))
    except ValueError as error:
        raise ValueError("The value must be a valid IPv4 or IPv6 address.") from error


def normalize_utc(value: datetime) -> datetime:
    """Convert an aware timestamp to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone.")
    return value.astimezone(UTC)


class CheckCreate(BaseModel):
    """A normalized successful lookup supplied by Backend."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    ip_address: str
    ip_version: int
    is_public: bool
    is_whitelisted: bool | None = None
    abuse_confidence_score: int = Field(ge=0, le=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    usage_type: str | None = Field(default=None, max_length=100)
    isp: str | None = Field(default=None, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    total_reports: int = Field(ge=0)
    num_distinct_users: int = Field(ge=0)
    last_reported_at: datetime | None = None
    max_age_days: int = Field(ge=1, le=365)
    source: str = Field(min_length=1, max_length=32)
    checked_at: datetime

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
        return normalize_ip(value)

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("last_reported_at", "checked_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return normalize_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_address_metadata(self) -> Self:
        parsed_address = ip_address(self.ip_address)
        if self.ip_version != parsed_address.version:
            raise ValueError("ip_version does not match ip_address.")
        if not self.is_public or not parsed_address.is_global:
            raise ValueError("ip_address must be public and is_public must be true.")
        return self


class HistoryRecord(BaseModel):
    """Serialized History record returned to callers."""

    history_id: int
    request_id: UUID
    ip_address: str
    ip_version: int
    is_public: bool
    is_whitelisted: bool | None
    abuse_confidence_score: int
    country_code: str | None
    usage_type: str | None
    isp: str | None
    domain: str | None
    total_reports: int
    num_distinct_users: int
    last_reported_at: datetime | None
    max_age_days: int
    source: str
    checked_at: datetime

    @classmethod
    def from_record(cls, record: IpCheckHistory) -> Self:
        """Convert an ORM record without exposing it through the API."""

        def as_utc(value: datetime | None) -> datetime | None:
            return value.replace(tzinfo=UTC) if value is not None else None

        checked_at = as_utc(record.checked_at)
        if checked_at is None:
            raise ValueError("Persisted checked_at cannot be null.")
        return cls(
            history_id=record.id,
            request_id=UUID(record.request_id),
            ip_address=record.ip_address,
            ip_version=record.ip_version,
            is_public=record.is_public,
            is_whitelisted=record.is_whitelisted,
            abuse_confidence_score=record.abuse_confidence_score,
            country_code=record.country_code,
            usage_type=record.usage_type,
            isp=record.isp,
            domain=record.domain,
            total_reports=record.total_reports,
            num_distinct_users=record.num_distinct_users,
            last_reported_at=as_utc(record.last_reported_at),
            max_age_days=record.max_age_days,
            source=record.source,
            checked_at=checked_at,
        )


class HistoryList(BaseModel):
    """One page of History records."""

    items: list[HistoryRecord]
    limit: int
    offset: int
    total: int


class HistoryListQuery(BaseModel):
    """Validated list query parameters."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    ip_address: str | None = None

    @field_validator("ip_address")
    @classmethod
    def normalize_filter_ip(cls, value: str | None) -> str | None:
        return normalize_ip(value) if value is not None else None


class ErrorDetail(BaseModel):
    """Stable error details."""

    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    """Stable API error envelope."""

    error: ErrorDetail
