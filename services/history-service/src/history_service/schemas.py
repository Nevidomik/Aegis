"""Pydantic contracts for the internal History API."""

from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from history_service.models import IpCheckHistory

MAX_COUNT = 2_147_483_647


def normalize_ip(value: str) -> str:
    """Return the canonical representation of a valid IP address."""
    try:
        return str(ip_address(value))
    except ValueError as error:
        raise ValueError("The value must be a valid IPv4 or IPv6 address.") from error


def normalize_public_ip(value: str) -> str:
    """Return the canonical representation of a globally routable IP address."""
    normalized = normalize_ip(value)
    parsed = ip_address(normalized)
    if (
        parsed.is_loopback
        or parsed.is_private
        or parsed.is_multicast
        or parsed.is_link_local
        or parsed.is_unspecified
        or not parsed.is_global
    ):
        raise ValueError("The IP address must be public.")
    return normalized


def normalize_utc(value: datetime) -> datetime:
    """Convert an aware timestamp to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone.")
    return value.astimezone(UTC)


class ApplicationCheckRequest(BaseModel):
    """Application-facing request for one reputation lookup."""

    model_config = ConfigDict(extra="forbid")

    ip_address: str = Field(min_length=1, max_length=100)
    max_age_days: int = Field(default=30, ge=1, le=365)


class ProviderReputationRequest(BaseModel):
    """Strict normalized request sent to Provider."""

    model_config = ConfigDict(extra="forbid")

    ip_address: StrictStr = Field(min_length=1, max_length=39)
    max_age_days: StrictInt = Field(ge=1, le=365)

    @field_validator("ip_address")
    @classmethod
    def require_canonical_public_ip(cls, value: str) -> str:
        normalized = normalize_public_ip(value)
        if normalized != value:
            raise ValueError("The IP address must use its canonical representation.")
        return normalized


class ProviderReputationResponse(BaseModel):
    """Provider-independent response returned by Provider."""

    model_config = ConfigDict(extra="forbid")

    ip_address: StrictStr = Field(min_length=1, max_length=39)
    ip_version: Literal[4, 6]
    is_public: StrictBool
    is_whitelisted: StrictBool | None = None
    abuse_confidence_score: StrictInt = Field(ge=0, le=100)
    country_code: StrictStr | None = Field(default=None, min_length=2, max_length=2)
    usage_type: StrictStr | None = Field(default=None, max_length=100)
    isp: StrictStr | None = Field(default=None, max_length=255)
    domain: StrictStr | None = Field(default=None, max_length=255)
    total_reports: StrictInt = Field(ge=0, le=MAX_COUNT)
    num_distinct_users: StrictInt = Field(ge=0, le=MAX_COUNT)
    last_reported_at: datetime | None = None
    max_age_days: StrictInt = Field(ge=1, le=365)
    source: StrictStr = Field(min_length=1, max_length=32)
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
        if (
            not self.is_public
            or parsed_address.is_loopback
            or parsed_address.is_private
            or parsed_address.is_multicast
            or parsed_address.is_link_local
            or parsed_address.is_unspecified
            or not parsed_address.is_global
        ):
            raise ValueError("ip_address must be public and is_public must be true.")
        return self


class CheckCreate(ProviderReputationResponse):
    """A normalized successful lookup ready for persistence."""

    request_id: UUID


class HistoryRecord(CheckCreate):
    """Serialized History record returned to callers."""

    history_id: StrictInt = Field(gt=0)

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
    model_config = ConfigDict(extra="forbid")

    limit: StrictInt = Field(ge=1, le=100)
    offset: StrictInt = Field(ge=0, le=MAX_COUNT)
    total: StrictInt = Field(ge=0, le=MAX_COUNT)


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

    model_config = ConfigDict(extra="forbid")

    code: StrictStr = Field(min_length=1, max_length=64)
    message: StrictStr = Field(min_length=1, max_length=500)
    request_id: StrictStr = Field(min_length=1, max_length=36)


class ErrorResponse(BaseModel):
    """Stable API error envelope."""

    error: ErrorDetail


class ProviderErrorResponse(BaseModel):
    """Strict error envelope returned by Provider."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
